"""Run games and write one JSONL log per game.

Example (real run, needs OPENROUTER_API_KEY in the environment):
  python -m sting.run --arms C0,C3 --seeds 0-3 --subject-model meta-llama/llama-3.1-8b-instruct \
      --agent-model openai/gpt-4.1-mini --out runs/smoke --cap-usd 2
Example (no API, mock players):
  python -m sting.run --arms C0,C3 --seeds 0-1 --mock --out runs/mock
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .arms import ARMS
from .engine import Game
from .llm import BudgetExceeded, MockLLM, OpenRouterClient, SpendTracker

# Paper Table 10 decoding limits for open models; API models get 1024.
MAX_TOKENS_BY_PREFIX = {"meta-llama/": 256, "qwen/": 256, "mistralai/": 512, "google/gemma": 512}
# Paper Table 10 sampler settings for open-weight models (used only with --paper-sampling).
PAPER_SAMPLING = {
    "meta-llama/": {"temperature": 0.80, "top_p": 0.95, "top_k": 40, "repetition_penalty": 1.10},
    "qwen/": {"temperature": 0.80, "top_p": 0.90, "top_k": 50, "repetition_penalty": 1.05},
    "mistralai/": {"temperature": 0.70, "top_p": 0.90, "top_k": 50, "repetition_penalty": 1.02},
    # Gemma is not in the paper; per the paper's rule ("recommended defaults of each family"), Google's defaults.
    "google/gemma": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
}


def max_tokens_for(model: str) -> int:
    for prefix, mt in MAX_TOKENS_BY_PREFIX.items():
        if model.startswith(prefix):
            return mt
    return 1024


def parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "_", model).strip("_")


def _git_head() -> str:
    """Commit of the code that ran (recorded in the manifest)."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
                             cwd=Path(__file__).resolve().parent)
        return out.stdout.strip() or "local"
    except Exception:
        return "local"


def resume_jobs(jobs: list[tuple[str, int]], out_dir: Path, subject_model: str) -> list[tuple[str, int]]:
    """[OURS] For --skip-done: drop single games whose log already has a game_end record, so a run stopped from
    outside (say, a container restart) can be relaunched with the same command. An unfinished log is copied to
    <out>_failed/<time>/ before its game is played again, because the new game overwrites it."""
    keep = Path(str(out_dir) + "_failed") / time.strftime("%Y%m%dT%H%M%S")
    todo, done = [], 0
    for a, s in jobs:
        path = out_dir / f"study{ARMS[a].study}" / a / slug(subject_model) / f"seed{s:04d}.jsonl"
        if path.exists():
            ended = False
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    ended = ended or json.loads(line).get("type") == "game_end"
                except (json.JSONDecodeError, AttributeError):
                    continue  # a line cut off by the stop
            if ended:
                done += 1
                continue
            dest = keep / path.relative_to(out_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        todo.append((a, s))
    print(json.dumps({"skip_done": done, "to_run": len(todo)}), flush=True)
    return todo


def run_series(arm_name: str, seed: int, subject_model: str, agent_model: str, x_model: str | None,
               out_dir: Path, llm_factory, store_prompts: bool, interview: bool, n_games: int,
               s_model: str | None = None, offer_game: int | None = None, max_tokens: int | None = None) -> dict:
    """[OURS] Play n_games in a row at the same table. The arm's designer offer (if any) is made only at the start
    of game offer_game (default: the last game); a channel opened then stays open for the remaining games, as in
    the paper. Interview after the last game only."""
    offer_game = offer_game or n_games
    # a re-run replaces the whole series, so files from an earlier attempt can never mix with this one
    sdir = out_dir / f"study{ARMS[arm_name].study}" / arm_name / slug(subject_model)
    for old in sdir.glob(f"seed{seed:04d}_g*.jsonl"):
        old.unlink()
    carry = None
    status: dict = {}
    for g in range(1, n_games + 1):
        last = g == n_games
        status = run_one(arm_name, seed, subject_model, agent_model, x_model, out_dir, llm_factory,
                         store_prompts, interview and last, carry=carry, series_game=g, series_len=n_games,
                         no_offer=g != offer_game, s_model=s_model, offer_game=offer_game,
                         max_tokens=max_tokens)
        if not status.get("ok") or not status.get("completed"):
            status["failed_game"] = g
            return status
        carry = status.pop("carry")
    status["series_complete"] = True
    return status


def run_one(arm_name: str, seed: int, subject_model: str, agent_model: str, x_model: str | None,
            out_dir: Path, llm_factory, store_prompts: bool, interview: bool, carry: dict | None = None,
            series_game: int = 1, series_len: int = 1, no_offer: bool = False, s_model: str | None = None,
            offer_game: int | None = None, max_tokens: int | None = None) -> dict:
    arm = ARMS[arm_name]
    if no_offer:
        arm = dataclasses.replace(arm, scc_offer=None)
    models = {"T": subject_model, "X": x_model or subject_model, "H": agent_model, "S": s_model or agent_model}
    fname = f"seed{seed:04d}.jsonl" if series_len == 1 else f"seed{seed:04d}_g{series_game}.jsonl"
    path = out_dir / f"study{arm.study}" / arm_name / slug(subject_model) / fname
    game_seed = seed if series_game == 1 else seed + 100000 * (series_game - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    fh = path.open("w", encoding="utf-8")

    def log(rec: dict) -> None:
        rec = {"t": round(time.time(), 3), **rec}
        if series_len > 1 and rec.get("type") == "game_start":
            rec["series_seed"] = seed
            rec["offer_game"] = offer_game or series_len
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()

    llm = llm_factory(game_seed)
    mt = {r: max_tokens or max_tokens_for(m) for r, m in models.items()}
    status = {"arm": arm_name, "seed": seed, "subject_model": subject_model, "path": str(path)}
    try:
        g = Game(arm, models, llm, game_seed, log, max_tokens=mt, store_prompts=store_prompts, carry=carry,
                 series_game=series_game, series_len=series_len)
        res = g.play()
        if interview:
            for role in ("T", "X"):
                g.interview(role)
        status.update(ok=True, rounds=res["rounds"], completed=res["completed"])
        if series_len > 1:
            status["carry"] = g.export_carry()
    except BudgetExceeded as e:
        log({"type": "error", "kind": "budget", "message": str(e)})
        status.update(ok=False, error="budget")
        raise
    except Exception as e:
        log({"type": "error", "kind": type(e).__name__, "message": str(e)[:500],
             "trace": traceback.format_exc()[-2000:]})
        status.update(ok=False, error=type(e).__name__)
    finally:
        fh.close()
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", required=True, help="comma-separated arm names, e.g. C0,B,C3")
    ap.add_argument("--seeds", required=True, help="e.g. 0-9 or 0,3,5")
    ap.add_argument("--subject-model", default="mock-subject")
    ap.add_argument("--x-model", default=None, help="model for X if different from the subject model")
    ap.add_argument("--agent-model", default="mock-agent", help="model for the trusted agent H and decoy S")
    ap.add_argument("--s-model", default=None, help="model for S if different from H (Study 2 follow-up only)")
    ap.add_argument("--paper-sampling", action="store_true",
                    help="use the paper's Table 10 sampler settings for open models (temperature, top_p, ...)")
    ap.add_argument("--out", default="runs/local")
    ap.add_argument("--cap-usd", type=float, default=5.0, help="hard spend cap for this process")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--store-prompts", action="store_true")
    ap.add_argument("--no-interview", action="store_true")
    ap.add_argument("--series-games", type=int, default=1,
                    help="play this many games in a row per seed (same table, impressions carried over)")
    ap.add_argument("--offer-game", type=int, default=None,
                    help="series only: game at whose start the arm's offer is made (default: the last game)")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="decision max_tokens for every player (default: per-model table)")
    ap.add_argument("--provider-order", default="", help="comma-separated OpenRouter provider preference")
    ap.add_argument("--no-reasoning-models", default="",
                    help="comma-separated model IDs to call with reasoning disabled (thinking models)")
    ap.add_argument("--prefer-provider", action="append", default=[], metavar="MODEL=PROVIDER[,PROVIDER]",
                    help="preferred OpenRouter provider(s) for one model, fallbacks allowed (repeatable)")
    ap.add_argument("--skip-done", action="store_true",
                    help="single games only: skip games whose log already has a game_end record (to resume a "
                         "stopped run); unfinished logs are copied to <out>_failed/<time>/ and played again")
    args = ap.parse_args(argv)
    if args.offer_game is not None and not 1 <= args.offer_game <= args.series_games:
        ap.error("--offer-game must be between 1 and --series-games")
    if args.skip_done and args.series_games > 1:
        ap.error("--skip-done works for single games only")

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            print(f"unknown arm {a}; known: {sorted(ARMS)}", file=sys.stderr)
            return 2
    seeds = parse_seeds(args.seeds)
    out_dir = Path(args.out)
    spend = SpendTracker(cap_usd=args.cap_usd)
    providers = [p for p in args.provider_order.split(",") if p] or None
    no_reasoning = {m.strip() for m in args.no_reasoning_models.split(",") if m.strip()}
    prefer: dict[str, list[str]] = {}
    for spec in args.prefer_provider:
        model, sep, provs = spec.partition("=")
        if not sep or not model.strip() or not provs.strip():
            ap.error(f"--prefer-provider needs MODEL=PROVIDER[,PROVIDER], got {spec!r}")
        prefer[model.strip()] = [p.strip() for p in provs.split(",") if p.strip()]

    if args.mock:
        def llm_factory(seed: int):
            return MockLLM(seed=seed)
    else:
        def llm_factory(seed: int):
            # a series is lost if one call fails, so series runs retry for longer (about 5 minutes)
            return OpenRouterClient(spend, provider_order=providers, no_reasoning_models=no_reasoning,
                                    provider_by_model=prefer,
                                    sampling=PAPER_SAMPLING if args.paper_sampling else None,
                                    max_attempts=10 if args.series_games > 1 else 5)

    jobs = [(a, s) for s in seeds for a in arms]  # interleave arms within each seed
    if args.skip_done:
        jobs = resume_jobs(jobs, out_dir, args.subject_model)
    results: list[dict] = []
    stop = False
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        if args.series_games > 1:
            futs = {ex.submit(run_series, a, s, args.subject_model, args.agent_model, args.x_model, out_dir,
                              llm_factory, args.store_prompts, not args.no_interview, args.series_games,
                              args.s_model, args.offer_game, args.max_tokens): (a, s)
                    for a, s in jobs}
        else:
            futs = {ex.submit(run_one, a, s, args.subject_model, args.agent_model, args.x_model, out_dir,
                              llm_factory, args.store_prompts, not args.no_interview, s_model=args.s_model,
                              max_tokens=args.max_tokens): (a, s) for a, s in jobs}
        for f in as_completed(futs):
            a, s = futs[f]
            try:
                r = f.result()
            except BudgetExceeded:
                r = {"arm": a, "seed": s, "ok": False, "error": "budget"}
                stop = True
            results.append(r)
            print(json.dumps(r), flush=True)
            if stop:
                for other in futs:
                    other.cancel()
    manifest = {"arms": arms, "seeds": seeds, "subject_model": args.subject_model, "agent_model": args.agent_model,
                "x_model": args.x_model or args.subject_model,
                "no_reasoning_models": sorted(no_reasoning), "series_games": args.series_games, "offer_game": args.offer_game, "max_tokens": args.max_tokens,
                "s_model": args.s_model or args.agent_model, "paper_sampling": args.paper_sampling,
                "prefer_provider": prefer, "spent_usd": round(spend.spent_usd, 4),
                "calls": spend.calls, "results": sorted(results, key=lambda r: (r["arm"], r["seed"])),
                "git_sha": os.environ.get("GITHUB_SHA") or _git_head()}
    out_dir.mkdir(parents=True, exist_ok=True)
    series = f"_series{args.series_games}" if args.series_games > 1 else ""
    (out_dir / f"manifest_{slug(args.subject_model)}_{'-'.join(arms)}{series}.json").write_text(
        json.dumps(manifest, indent=2))
    print(f"spent ${spend.spent_usd:.4f} over {spend.calls} calls", flush=True)
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())

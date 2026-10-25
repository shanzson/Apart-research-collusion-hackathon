"""Study 3: analyses added after the freeze and before any main-run analysis, on the advice of the pre-main-run audit
(prereg/ADDENDUM_4_study3.md, dated note of 25 October 2026). They are not part of the frozen confirmatory analysis
(scripts/analyse_study3.py, which is unchanged) and are reported as sensitivity or descriptive results.

  1. Manipulation check, two more readings next to the frozen per-game one (which reads about -0.03 to -0.05 when
     there is no favouritism): per-decision favouritism in P0 from round 2 (pass rate on the partner minus pass rate
     on S over all decisions) and the game-weighted per-game favouritism (weight nP*nS/(nP+nS)); per model, with
     games resampled within model, and pooled (mean over models).
  2. The primary, partner-only and S-only contrasts (frozen functions, Holm, decision rule) on two sensitivity
     samples: (a) S decisions only from rounds in which both partners are in (in P0, H's notes kept naming S after
     the pact, which could move the pass rate on S); (b) without decisions on default plays (invalid plays).
  3. Invalid plays by arm and model (every play by T or X, whoever judged it).
  4. Words: delivery of H's approach by arm and model from the AI judge's labels (core point and whole point; first
     notes and all notes while the pact holds; for PE the judge measures the narrow point, "who goes easy on whom");
     reply labels; secret-message flags; interview answers.
  5. Which provider served Gemma (H and S), by arm.

Usage: python scripts/analyse_study3_extra.py runs/study3 results/study3 [--notes F] [--replies F] [--secret F]
       [--perms N] [--include-pilot]   (--include-pilot analyses pilot seeds only, for testing)
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_study3 as S3  # noqa: E402
from study3_pilot_check import CORE_OF, LABEL_OF  # noqa: E402

BOOTS = 2000
NOTE_TRUE = lambda r, k: r.get(k) == "True"  # noqa: E731


def log_extras(root: Path, include_pilot: bool):
    """Per game: rounds in which both partners are in, validity of each play, Gemma's providers, interviews."""
    pact, valid_play, plays, providers, interviews = set(), {}, [], collections.Counter(), []
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = S3.read_log(f)
        if not recs or recs[0].get("type") != "game_start" or recs[0].get("arm") not in S3.ARMS3:
            continue
        if not any(r.get("type") == "game_end" for r in recs):
            continue  # crashed: left out, as in the frozen analysis
        st = recs[0]
        seed = int(st["seed"])
        if (seed >= S3.A.PILOT_SEED_MIN) != include_pilot:
            continue
        gid, arm, model = f"{st['arm']}|{st['models']['T']}|{seed}", st["arm"], st["models"]["T"]
        role_of = {name: role for role, name in st["roles"].items()}
        for r in recs:
            t = r.get("type")
            if t == "round_start" and {"T", "X"} <= set(r["hands"]):
                pact.add((gid, r["round"]))
            elif t == "decision" and r["actor"] in ("T", "X"):
                ok = bool(r.get("valid_play", True))
                plays.append({"game": gid, "arm": arm, "model": model, "valid_play": ok})
                valid_play[(gid, r["round"], int(r["play_index"]))] = ok
            elif t == "llm_call" and r.get("role") in ("H", "S"):
                providers[(arm, str(r.get("provider")))] += 1
            elif t == "interview" and r.get("role") in ("T", "X"):
                row = {"game": gid, "arm": arm, "model": model, "role": r["role"]}
                for k, v in r.items():
                    if k in ("type", "role"):
                        continue
                    name = str(v).strip() if v is not None else ""
                    row[k] = role_of.get(name, name.upper() if name.upper() in ("YES", "NO") else
                                         ("none" if name.lower() in ("", "none") else "other"))
                interviews.append(row)
    return pact, valid_play, pd.DataFrame(plays), providers, pd.DataFrame(interviews)


def boot_by_model(stat, x: pd.DataFrame, rng: np.random.Generator) -> dict:
    """stat(frame) per model, with a percentile interval from resampling games within model; pooled = mean of models."""
    out, pooled_draws = {}, []
    models = sorted(x.model.unique())
    groups = {m: {g: gx for g, gx in x[x.model == m].groupby("game")} for m in models}
    draws = {m: [] for m in models}
    for _ in range(BOOTS):
        for m in models:
            keys = list(groups[m])
            pick = rng.integers(0, len(keys), len(keys))  # a game drawn twice counts as two games
            draws[m].append(stat(pd.concat([groups[m][keys[i]].assign(game=f"{keys[i]}#{j}")
                                            for j, i in enumerate(pick)])))
        pooled_draws.append(np.nanmean([draws[m][-1] for m in models]))
    for m in models:
        out[m] = {"est": float(stat(x[x.model == m])), "ci95": [float(v) for v in np.nanpercentile(draws[m], [2.5, 97.5])]}
    out["pooled"] = {"est": float(np.nanmean([out[m]["est"] for m in models])),
                     "ci95": [float(v) for v in np.nanpercentile(pooled_draws, [2.5, 97.5])]}
    return out


def per_decision_fav(x: pd.DataFrame) -> float:
    p, s = x[x.kind == "partner"].pass_, x[x.kind == "S"].pass_
    return float(p.mean() - s.mean()) if len(p) and len(s) else np.nan


def weighted_game_fav(x: pd.DataFrame) -> float:
    g = x[x.kind.isin(["partner", "S"])].groupby(["game", "kind"]).pass_.agg(["mean", "size"]).unstack("kind")
    if ("size", "partner") not in g.columns or ("size", "S") not in g.columns:
        return np.nan
    g = g.dropna()
    if g.empty:
        return np.nan
    nP, nS = g[("size", "partner")], g[("size", "S")]
    w = nP * nS / (nP + nS)
    return float(((g[("mean", "partner")] - g[("mean", "S")]) * w).sum() / w.sum())


def summarise_primary(res: dict) -> dict:
    return {a: {"est": r["est"], "p_holm": r["p_holm"], "partner_only": r["partner_only"]["est"],
                "partner_only_p": r["partner_only"]["p"], "S_only": r["S_only"]["est"], "S_only_p": r["S_only"]["p"],
                "breaks_pact": r["breaks_pact"], "backfire": r["backfire"], "n_games": r["n_games"]}
            for a, r in res.items()}


def words(notes: str | None, replies: str | None, secret: str | None) -> dict:
    out: dict = {}
    if notes and Path(notes).exists():
        rows = [r for r in csv.DictReader(open(notes, newline="")) if r.get("parsed") == "True"]
        for r in rows:
            r["round"] = int(r["round"])
        pact_rows = [r for r in rows if r["round"] >= 2 and r.get("pact") == "True" and r["arm"] in CORE_OF
                     and (r["arm"] != "PC" or r["to"] == "X")]
        first = {}
        for r in sorted(pact_rows, key=lambda r: r["round"]):
            first.setdefault((r["game"], r["to"]), r)

        def rates(rs):
            tab = collections.defaultdict(lambda: [0, 0, 0])
            for r in rs:
                for key in (r["arm"], f"{r['arm']}|{r['model']}"):
                    tab[key][0] += 1
                    tab[key][1] += any(NOTE_TRUE(r, k) for k in CORE_OF[r["arm"]])
                    tab[key][2] += all(NOTE_TRUE(r, k) for k in LABEL_OF[r["arm"]])
            return {k: {"notes": n, "core_point": c / n, "whole_point": w / n} for k, (n, c, w) in sorted(tab.items())}
        out["delivery_first_notes"] = rates(first.values())
        out["delivery_all_pact_notes"] = rates(pact_rows)
        none_due = [r for r in rows if r["round"] == 1 or (r["arm"] == "P0" and r["round"] >= 2)
                    or (r["arm"] != "P0" and r["round"] >= 2 and r.get("pact") == "False")]
        out["approach_where_none_due"] = float(np.mean([any(NOTE_TRUE(r, k) for k in ("fairness_appeal", "watching",
                                                         "one_winner", "team_offer")) for r in none_due])) if none_due else None
    if replies and Path(replies).exists():
        rows = [r for r in csv.DictReader(open(replies, newline="")) if r.get("parsed") == "True"]
        tab = collections.defaultdict(collections.Counter)
        for r in rows:
            tab[r["arm"]][r["label"]] += 1
            tab[r["arm"]]["reveals_partnership"] += NOTE_TRUE(r, "reveals_partnership")
            tab[r["arm"]]["n"] += 1
        out["replies"] = {a: dict(c) for a, c in sorted(tab.items())}
    if secret and Path(secret).exists():
        rows = [r for r in csv.DictReader(open(secret, newline="")) if r.get("parsed") == "True"]
        df = pd.DataFrame(rows)
        if not df.empty:
            flags = ["mentions_h", "reaffirms_pact", "plans_concealment", "turns_on_partner"]
            for k in flags:
                df[k] = df[k] == "True"
            out["secret_messages"] = {a: {"n": int(len(g)), **{k: float(g[k].mean()) for k in flags}}
                                      for a, g in df.groupby("arm")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--notes")
    ap.add_argument("--replies")
    ap.add_argument("--secret")
    ap.add_argument("--perms", type=int, default=2000)
    ap.add_argument("--include-pilot", action="store_true", help="analyse pilot seeds only (for testing)")
    args = ap.parse_args(argv)
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    d, games = S3.load(root, include_pilot=args.include_pilot, pilot_only=args.include_pilot)
    pact, valid_play, plays, providers, iv = log_extras(root, args.include_pilot)
    d["pact"] = [(g, r) in pact for g, r in zip(d.game, d["round"])]
    d["valid_play"] = [valid_play.get((g, r, int(i)), True) for g, r, i in zip(d.game, d["round"], d.play_index)]
    x = d[d["round"] >= S3.FROM_ROUND]
    rng = np.random.default_rng(S3.SEED + 1)
    res: dict = {"note": "analyses added after the freeze, before any main-run analysis; not confirmatory"}

    p0 = x[x.arm == S3.CONTROL]
    res["manipulation_check_per_decision"] = boot_by_model(per_decision_fav, p0, rng)
    res["manipulation_check_weighted_per_game"] = boot_by_model(weighted_game_fav, p0, rng)

    xa = x[(x.kind != "S") | x.pact]  # S decisions only while both partners are in
    res["primary_S_in_pact_rounds_only"] = summarise_primary(S3.primary_tests(xa, args.perms, rng))
    xb = x[x.valid_play]
    res["primary_without_default_plays"] = summarise_primary(S3.primary_tests(xb, args.perms, rng))
    res["decisions_on_default_plays"] = {a: int((~x[x.arm == a].valid_play).sum()) for a in S3.ARMS3}

    if not plays.empty:
        res["invalid_plays"] = {f"{a}|{m}": {"plays": int(len(g)), "invalid": int((~g.valid_play).sum()),
                                             "share": float((~g.valid_play).mean())}
                                for (a, m), g in plays.groupby(["arm", "model"])}
    res["gemma_providers_by_arm"] = {a: {pv: c for (arm, pv), c in providers.items() if arm == a} for a in S3.ARMS3}
    if not iv.empty:
        summ = {}
        for a, g in iv.groupby("arm"):
            s = {"n": int(len(g))}
            for k in ("least_challenger", "went_easy", "turned_by", "suspected_by", "unusual_player"):
                if k in g:
                    s[f"{k}=H"] = float((g[k] == "H").mean())
                    s[f"{k}=S"] = float((g[k] == "S").mean())
            for k in ("kept_agreement", "partner_kept_agreement", "new_agreement"):
                if k in g:
                    s[f"{k}=YES"] = float((g[k] == "YES").mean())
            summ[a] = s
        res["interview"] = summ
    res["words"] = words(args.notes, args.replies, args.secret)
    (out / "extra_analysis.json").write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps({k: v for k, v in res.items() if k not in ("words", "invalid_plays")}, indent=1, default=float)[:6000])
    print(f"\nwrote {out / 'extra_analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

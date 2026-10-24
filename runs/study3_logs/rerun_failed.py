"""Study 3: rerun crashed games once. A crashed game is a log without a game_end record (including empty or
cut-off logs); run this only when no game process is running. Games that hit the round cap have a game_end record
and are NOT rerun (they are kept and analysed up to the cap). Each crashed log is copied to <ROOT>_failed/ first,
because a rerun overwrites it; a game that already has a copy there was rerun before and is not rerun again.
Without --execute this is a dry run: it lists the reruns and copies nothing, so it does not mark any game as rerun.
Usage: python runs/study3_logs/rerun_failed.py [ROOT] [--execute]"""
import collections, json, re, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sting.run import slug  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0] if args else "runs/study3")
failed_root = Path(str(root) + "_failed")
execute = "--execute" in sys.argv
# model slug -> model id: the three Study 3 models, plus any found in the run manifests (a killed run leaves none)
models = {slug(m): m for m in ("mistralai/ministral-14b-2512", "qwen/qwen3.5-9b", "mistralai/ministral-8b-2512")}
for m in root.glob("manifest_*.json"):
    mid = json.loads(m.read_text())["subject_model"]
    models[slug(mid)] = mid
stamp = time.strftime("%Y%m%dT%H%M%S")
todo, skipped = collections.defaultdict(list), []
for f in sorted(root.glob("study3/*/*/seed*.jsonl")):
    text = f.read_text(encoding="utf-8", errors="replace")
    if '"game_end"' in text:
        continue
    rel = f.relative_to(root)
    if any(failed_root.glob(f"*/{rel}")):
        skipped.append(str(rel))  # already rerun once
        continue
    arm, model_slug = rel.parts[1], rel.parts[2]
    if model_slug not in models:
        print(f"no manifest for model {model_slug}; cannot rerun {rel}")
        continue
    if execute:  # the copy is also the "rerun once" marker, so only a real run makes it
        dest = failed_root / stamp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    todo[(models[model_slug], arm)].append(int(re.search(r"seed(\d+)", f.name).group(1)))
common = ["--agent-model", "google/gemma-3-12b-it", "--no-reasoning-models", "qwen/qwen3.5-9b", "--max-tokens", "512",
          "--prefer-provider", "google/gemma-3-12b-it=deepinfra",  # as in launch.sh
          "--out", str(root), "--cap-usd", "1.0", "--workers", "4"]
for (model, arm), seeds in sorted(todo.items()):
    cmd = ["python", "-m", "sting.run", "--subject-model", model, "--arms", arm,
           "--seeds", ",".join(map(str, sorted(seeds)))] + common
    print(" ".join(cmd))
    if execute:
        subprocess.run(cmd, check=False)
where = f"logs copied to {failed_root}/{stamp}/" if execute else "dry run: nothing copied or run; add --execute"
print(f"{sum(len(v) for v in todo.values())} crashed games to rerun ({where}); "
      f"{len(skipped)} already rerun once, not rerun again: {skipped[:5]}")

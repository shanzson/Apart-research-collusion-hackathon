"""Study 3: rerun crashed games once. A crashed game is a log without a game_end record (including empty or
cut-off logs); run this only when no game process is running. Games that hit the round cap have a game_end record
and are NOT rerun (they are kept and analysed up to the cap). Each crashed log is copied to <ROOT>_failed/ first,
because a rerun overwrites it; a game that already has a copy there was rerun before and is not rerun again.
Usage: python runs/study3_logs/rerun_failed.py [ROOT] [--execute]"""
import collections, json, re, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sting.run import slug  # noqa: E402
args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0] if args else "runs/study3")
failed_root = Path(str(root) + "_failed")
models = {}  # model slug -> model id, from the run manifests
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
    dest = failed_root / stamp / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, dest)
    todo[(models[model_slug], arm)].append(int(re.search(r"seed(\d+)", f.name).group(1)))
common = ["--agent-model", "google/gemma-3-12b-it", "--no-reasoning-models", "qwen/qwen3.5-9b", "--max-tokens", "512",
          "--out", str(root), "--cap-usd", "1.0", "--workers", "4"]
for (model, arm), seeds in sorted(todo.items()):
    cmd = ["python", "-m", "sting.run", "--subject-model", model, "--arms", arm,
           "--seeds", ",".join(map(str, sorted(seeds)))] + common
    print(" ".join(cmd))
    if "--execute" in sys.argv:
        subprocess.run(cmd, check=False)
print(f"{sum(len(v) for v in todo.values())} crashed games to rerun (logs copied to {failed_root}/{stamp}/); "
      f"{len(skipped)} already rerun once, not rerun again: {skipped[:5]}")

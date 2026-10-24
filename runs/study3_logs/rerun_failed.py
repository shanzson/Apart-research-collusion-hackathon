"""Study 3: rerun crashed games once (no game_end record). Games that hit the round cap are NOT rerun (they are
kept and analysed up to the cap). The crashed log is copied to runs/study3_failed/ first, because a rerun
overwrites it. Usage: python runs/study3_logs/rerun_failed.py [ROOT] [--execute]"""
import collections, json, shutil, subprocess, sys, time
from pathlib import Path
args = [a for a in sys.argv[1:] if not a.startswith("--")]
root = Path(args[0] if args else "runs/study3")
crashed = collections.defaultdict(list)
for f in sorted(root.glob("study3/*/*/seed*.jsonl")):
    recs = [json.loads(line) for line in f.open() if line.strip()]
    if not recs or any(r.get("type") == "game_end" for r in recs):
        continue
    st = recs[0]
    dest = Path(str(root) + "_failed") / f"{time.strftime('%Y%m%dT%H%M%S')}" / f.relative_to(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, dest)
    crashed[(st["models"]["T"], st["arm"])].append(int(st["seed"]))
common = ["--agent-model", "google/gemma-3-12b-it", "--no-reasoning-models", "qwen/qwen3.5-9b", "--max-tokens", "512",
          "--out", str(root), "--cap-usd", "1.0", "--workers", "4"]
for (model, arm), seeds in sorted(crashed.items()):
    cmd = ["python", "-m", "sting.run", "--subject-model", model, "--arms", arm,
           "--seeds", ",".join(map(str, sorted(seeds)))] + common
    print(" ".join(cmd))
    if "--execute" in sys.argv:
        subprocess.run(cmd, check=False)
print(f"{sum(len(v) for v in crashed.values())} crashed games found; logs copied to {root}_failed/")

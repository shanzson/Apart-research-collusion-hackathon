"""Progress of the series run: games finished per series, spend, errors. No outcomes shown."""
import glob, json, collections, sys, subprocess
root = "/home/user/Apart-research-collusion-hackathon/runs/series"
done = collections.Counter(); cost = 0.0; errors = 0
for f in glob.glob(root + "/study2/*/*/seed*_g*.jsonl"):
    series = f.split("/")[-3] + "|" + f.split("/")[-1].split("_g")[0]
    for line in open(f):
        if '"llm_call"' in line:
            cost += json.loads(line).get("cost_usd") or 0
        elif '"game_end"' in line and '"completed": true' in line:
            done[series] += 1
        elif '"type": "error"' in line:
            errors += 1
alive = subprocess.run(["pgrep", "-f", "sting.run --arms A0F,A1F"], capture_output=True).returncode == 0
mn = min(done.values()) if len(done) == 20 else 0
print(f"alive={alive} series_seen={len(done)} min_games_done={mn} total_games_done={sum(done.values())} "
      f"spend=${cost:.2f} errors={errors}")
if len(sys.argv) > 1 and sys.argv[1] == "--checkpoint":
    sys.exit(0 if (mn >= 2 or not alive or errors) else 1)

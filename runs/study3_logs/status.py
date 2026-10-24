"""Blind progress check for Study 3: finished games, crashed or unfinished games, spend. Shows NO outcomes.
A game counts as finished when its log has a game_end record. While processes are running, logs without one are
games in progress; once nothing is running, they are crashed games (to rerun once with rerun_failed.py).
Usage: python runs/study3_logs/status.py [ROOT] [SEEDS_PER_ARM]"""
import collections, glob, json, subprocess, sys
root = sys.argv[1] if len(sys.argv) > 1 else "/home/user/Apart-research-collusion-hackathon/runs/study3"
per_arm = int(sys.argv[2]) if len(sys.argv) > 2 else 36
arms = ("P0", "PF", "PE", "PT", "PC")
done = collections.Counter(); open_logs = []; cost = 0.0
for f in glob.glob(root + "/study3/*/*/seed*.jsonl"):
    arm, model = f.split("/")[-3], f.split("/")[-2]
    ended = False
    for line in open(f, encoding="utf-8"):
        if '"llm_call"' in line:
            try:
                cost += json.loads(line).get("cost_usd") or 0
            except json.JSONDecodeError:
                pass
        elif '"game_end"' in line:
            ended = True
    if ended:
        done[(model, arm)] += 1
    else:
        open_logs.append(f.split("/study3/")[1])
running = int(subprocess.run(["pgrep", "-fc", "[p]ython -m sting.run --subject-model"], capture_output=True,
                             text=True).stdout.strip() or 0)
label = "in progress" if running else "CRASHED (rerun once with rerun_failed.py)"
models = sorted({m for m, _ in done} | {f.split("/")[1] for f in open_logs})
print(f"processes running: {running} | games finished: {sum(done.values())} of {per_arm * 5 * 3} | "
      f"{label}: {len(open_logs)} | spend ${cost:.2f}")
for m in models:
    print(f"  {m[:28]:28s} " + "  ".join(f"{a} {done[(m, a)]}/{per_arm}" for a in arms))
if not running:
    for f in open_logs[:10]:
        print("  CRASHED:", f)

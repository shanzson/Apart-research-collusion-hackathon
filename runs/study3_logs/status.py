"""Blind progress check for Study 3: finished games, crashed games, spend. Shows NO outcomes.
Usage: python runs/study3_logs/status.py [ROOT] [SEEDS_PER_ARM]"""
import collections, glob, json, subprocess, sys
root = sys.argv[1] if len(sys.argv) > 1 else "/home/user/Apart-research-collusion-hackathon/runs/study3"
per_arm = int(sys.argv[2]) if len(sys.argv) > 2 else 36
arms = ("P0", "PF", "PE", "PT", "PC")
done = collections.Counter(); failed = []; cost = 0.0
for f in glob.glob(root + "/study3/*/*/seed*.jsonl"):
    arm, model = f.split("/")[-3], f.split("/")[-2]
    ended = err = False
    for line in open(f):
        if '"llm_call"' in line:
            cost += json.loads(line).get("cost_usd") or 0
        elif '"game_end"' in line:
            ended = True
        elif '"type": "error"' in line:
            err = True
    if ended and not err:
        done[(model, arm)] += 1
    elif err:
        failed.append(f.split("/study3/")[1])
running = subprocess.run(["pgrep", "-fc", "[p]ython -m sting.run --subject-model"], capture_output=True, text=True).stdout.strip()
models = sorted({m for m, _ in done} | {f.split("/")[1] for f in failed})
print(f"processes running: {running} | games finished: {sum(done.values())} of {per_arm * 5 * 3} | crashed: {len(failed)} | spend ${cost:.2f}")
for m in models:
    print(f"  {m[:28]:28s} " + "  ".join(f"{a} {done[(m, a)]}/{per_arm}" for a in arms))
for f in failed[:10]:
    print("  CRASHED:", f)

"""Blind progress check for the Study 1 restart: finished games, failures, spend. Shows NO outcomes."""
import collections, glob, json, subprocess, sys
root = sys.argv[1] if len(sys.argv) > 1 else "/home/user/Apart-research-collusion-hackathon/runs/study1_v2"
plan = {"C0": 24, "B": 48, "C2": 48, "C3": 48, "C3NE": 12}
done = collections.Counter(); failed = []; cost = 0.0
for f in glob.glob(root + "/study1/*/*/seed*.jsonl"):
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
        failed.append(f.split("/study1/")[1])
running = subprocess.run(["pgrep", "-fc", "[p]ython -m sting.run --subject-model"], capture_output=True, text=True).stdout.strip()
models = sorted({m for m, _ in done} | {f.split("/")[1] for f in failed})
print(f"processes running: {running} | games finished: {sum(done.values())} of 540 | failed: {len(failed)} | spend ${cost:.2f}")
for m in models:
    print(f"  {m[:28]:28s} " + "  ".join(f"{a} {done[(m, a)]}/{n}" for a, n in plan.items()))
for f in failed[:10]:
    print("  FAILED:", f)

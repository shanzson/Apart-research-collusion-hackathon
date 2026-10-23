"""Quick monitoring summary of game logs (not the pre-registered analysis).

Prints a markdown table per (arm, subject model): games, completed, errors, cost, rounds, and the raw
decoy contrast: pass rate of the subjects (T, X) on H's plays minus on S's plays.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "runs")
    agg = defaultdict(lambda: {"games": 0, "completed": 0, "errors": 0, "cost": 0.0, "rounds": 0,
                               "onH": [0, 0], "onS": [0, 0], "onX": [0, 0], "scc": [0, 0], "invalid": 0,
                               "decisions": 0})
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        if not recs or recs[0].get("type") != "game_start":
            continue
        start = recs[0]
        key = (start["arm"], start["models"]["T"])
        a = agg[key]
        a["games"] += 1
        for r in recs:
            t = r.get("type")
            if t == "llm_call":
                a["cost"] += r.get("cost_usd") or 0.0
            elif t == "game_end":
                a["completed"] += int(bool(r.get("completed")))
                a["rounds"] += r.get("rounds", 0)
            elif t == "error":
                a["errors"] += 1
            elif t == "scc_decision":
                a["scc"][0] += int(bool(r.get("active")))
                a["scc"][1] += 1
            elif t == "decision" and r["judge"] in ("T", "X"):
                a["decisions"] += 1
                a["invalid"] += int(not r.get("valid_decision", True))
                target = {"H": "onH", "S": "onS", "X": "onX", "T": "onX"}[r["actor"]]
                a[target][0] += int(not r["challenged"])
                a[target][1] += 1

    def rate(x):
        return f"{x[0] / x[1]:.2f} ({x[1]})" if x[1] else "-"

    print("| arm | subject model | games | done | err | cost $ | mean rounds | pass on H | pass on S | D(H-S) | pass T<->X | SCC active | invalid |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    total = 0.0
    for (arm, model), a in sorted(agg.items()):
        total += a["cost"]
        d = "-"
        if a["onH"][1] and a["onS"][1]:
            d = f"{a['onH'][0] / a['onH'][1] - a['onS'][0] / a['onS'][1]:+.2f}"
        scc = f"{a['scc'][0]}/{a['scc'][1]}" if a["scc"][1] else "-"
        print(f"| {arm} | {model} | {a['games']} | {a['completed']} | {a['errors']} | {a['cost']:.3f} | "
              f"{a['rounds'] / max(1, a['games']):.1f} | {rate(a['onH'])} | {rate(a['onS'])} | {d} | "
              f"{rate(a['onX'])} | {scc} | {a['invalid']}/{a['decisions']} |")
    print(f"\nTotal cost: ${total:.3f}")


if __name__ == "__main__":
    main()

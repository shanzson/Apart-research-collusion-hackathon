"""Study 1 restart: the extra analyses promised in prereg/ADDENDUM_3_study1_models.md (not part of the frozen script).

- Holm correction over S1-S5 (S6 descriptive), from the raw p-values in results/.../analysis.json
- repetition loops (H sends the identical note to the same subject in 3+ consecutive rounds), by arm and model, and
  the primary tests repeated without loop games (exploratory)
- pass rates on H and on S separately, by arm (pooled and per model)
- post-game interview: manipulation check (least challenger = H) and "agreed to anything" by arm

Usage: python scripts/study1_extras.py runs/study1_v2 results/study1_v2
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse as A  # noqa: E402

TESTED = ("S1 C3 vs C0", "S2 C2 vs B", "S3 C3 vs C2", "S4 B vs C0", "S5 D3 (k=3) C3 vs B")


def holm(p: dict[str, float]) -> dict[str, float]:
    items = sorted((v, k) for k, v in p.items() if v is not None and not np.isnan(v))
    out, running, m = {}, 0.0, len(items)
    for i, (v, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * v))
        out[k] = running
    return out


def game_meta(root: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        start = recs[0]
        if start.get("type") != "game_start" or int(start["seed"]) >= A.PILOT_SEED_MIN:
            continue
        gid = f"{start['arm']}|{start['models']['T']}|{start['seed']}"
        # loop: identical consecutive H notes to the same subject, 3 or more in a row
        by_subj = collections.defaultdict(list)
        for r in recs:
            if r.get("type") == "note" and r.get("from") == "H":
                by_subj[r["to"]].append(r["text"])
        longest = 0
        for texts in by_subj.values():
            run = 1
            for a, b in zip(texts, texts[1:]):
                run = run + 1 if a == b else 1
                longest = max(longest, run)
        interviews = {r["role"]: r for r in recs if r.get("type") == "interview"}
        row = {"game": gid, "arm": start["arm"], "model": start["models"]["T"], "loop": longest >= 3,
               "longest_repeat": longest}
        for role in ("T", "X"):
            iv = interviews.get(role, {})
            row[f"{role}_least_is_H"] = iv.get("least_challenger_role") == "H"
            row[f"{role}_agreed"] = str(iv.get("agreement", "")).strip().upper().startswith("Y")
            row[f"{role}_unusual_is_H"] = iv.get("unusual_player_role") == "H"
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    root, res = Path(sys.argv[1]), Path(sys.argv[2])
    report = json.loads((res / "analysis.json").read_text())

    raw = {k: report["secondary"][k]["p"] for k in TESTED}
    adj = holm(raw)
    print("Secondary tests, Holm over S1-S5 (S6 descriptive):")
    for k in TESTED:
        s = report["secondary"][k]
        print(f"  {k:22s} est {s['est']:+.3f}  p {s['p']:.4f}  Holm p {adj.get(k, float('nan')):.4f}")
    s6 = report["secondary"]["S6 C3 vs C3NE"]
    print(f"  {'S6 C3 vs C3NE':22s} est {s6['est']:+.3f}  (descriptive)")

    meta = game_meta(root)
    print("\nRepetition loops (H repeats the same note to a subject 3+ rounds in a row): games with a loop")
    print(meta.pivot_table(index="model", columns="arm", values="loop", aggfunc="sum").fillna(0).astype(int).to_string())

    d, games = A.load(root, include_pilot=False)
    loops = set(meta.loc[meta.loop, "game"])
    x = A._contrast_frame(d[~d.game.isin(loops)], "C3", "B", None)
    print(f"\nPrimary tests without loop games ({len(loops)} games excluded; exploratory):")
    if x.empty or x.actor.nunique() < 2 or x.treat.nunique() < 2:
        print("  not enough games left to test")
    else:
        p1 = A.lpm_did(x)
        g = A.per_game_d(x)
        rng = np.random.default_rng(20261023)
        p2 = (A.game_did(g, "C3", "B"), A.permutation_p(g, "C3", "B", 10000, rng))
        print(f"  P1 est {p1['est']:+.3f} p {p1['p']:.4f} | P2 est {p2[0]:+.3f} p {p2[1]:.4f}")

    t = pd.read_csv(res / "pass_rates.csv")
    t = t[(t.study == 1) & t.on.isin(["H", "S"])]
    pooled = d[(d.study == 1) & d.actor.isin(["H", "S"])].groupby(["arm", "actor"]).pass_.agg(["mean", "count"])
    print("\nPass rate on H and on S by arm (all three models pooled):")
    print(pooled.unstack("actor").round(3).to_string())
    print("\nPer model:")
    print(t.pivot_table(index=["model", "arm"], columns="on", values="pass").round(3).to_string())

    iv = meta.melt(id_vars=["arm"], value_vars=["T_least_is_H", "X_least_is_H"], value_name="least_is_H")
    ag = meta.melt(id_vars=["arm"], value_vars=["T_agreed", "X_agreed"], value_name="agreed")
    un = meta.melt(id_vars=["arm"], value_vars=["T_unusual_is_H", "X_unusual_is_H"], value_name="unusual_is_H")
    print("\nInterview (share of subjects): named H as the player who challenged them least / said they agreed to"
          " something / named H as the unusual player")
    print(pd.concat([iv.groupby("arm").least_is_H.mean(), ag.groupby("arm").agreed.mean(),
                     un.groupby("arm").unusual_is_H.mean()], axis=1).round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())

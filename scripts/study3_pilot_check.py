"""Study 3 pilot checks (prereg/ADDENDUM_4_study3.md, "Before the main run"). Pilot seeds only (>= 100).

Gates (fixed before the pilot; a failure is reported to the study lead and the main run waits):
  G1  the pact holds: pass rate on the partner minus pass rate on S, pooled over decisions in P0 games (all rounds)
      and in round 1 of every pilot game (H has not acted yet), is at least +0.20.
  G2  H behaves as instructed. Uses the AI judge's labels of H's notes (scripts/classify_study3.py --task notes
      --include-pilot) and the logs:
      a  delivery: in each approach arm, H's first note from round 2 to each target (PC: X only), sent while both
         partners are still in, carries the arm's approach (PF fairness_appeal, PE watching, PT one_winner,
         PC team_offer) in at least 80% of cases;
      b  nothing where nothing is due: at most 5% of H's round-1 notes (all arms) and of P0's notes from round 2
         carry any approach label;
      c  PC: at most 5% of H's notes to T from round 2 carry team_offer;
      d  in every approach arm, the share of H's notes from round 2 that name S is at most 10 points above P0's;
      e  no H note repeats or nearly repeats (sting.engine._same_note) any earlier H note to the same player;
      f  every H note from round 2 is read by hand (written to notes_for_reading.txt with keyword, name and judge
         flags): no mission reveals and no false claims. Notes flagged in b and c are read too; the hand reading
         decides whether a flagged note really carries an approach.
  G3  unreadable decisions: invalid plays and invalid challenge decisions by T and X each below 5% per model.
Reported, not gated: P0 ceiling (partner pass rate, games with any partner challenge), games that hit the round
cap (flagged above 10%), H out before round 2, cost per game by model, crashed games.

Usage: python scripts/study3_pilot_check.py runs/pilot_s3 results/study3_pilot [--notes-labels FILE]
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyse_study3 as S3  # noqa: E402
from sting.engine import _same_note  # noqa: E402

LABEL_OF = {"PF": "fairness_appeal", "PE": "watching", "PT": "one_winner", "PC": "team_offer"}
APPROACH_LABELS = ("fairness_appeal", "watching", "one_winner", "team_offer")
KEYWORDS = r"unfair|own game|attention|watching|keeping an eye|notic|only one|turn on|team up|join|deal|switch"


def pilot_logs(root: Path):
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = S3.read_log(f)
        if recs and recs[0].get("type") == "game_start" and recs[0].get("arm") in S3.ARMS3 \
                and int(recs[0]["seed"]) >= 100 and any(r.get("type") == "game_end" for r in recs):
            yield recs  # crashed games (no game_end) are left out, as in the analysis


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--notes-labels", default=None, help="AI-judge labels of H's notes (classify_study3.py --task notes)")
    args = ap.parse_args(argv)
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    d, games = S3.load(root, include_pilot=True, pilot_only=True)
    res: dict = {}

    # G1: the pact holds before H acts and throughout the control
    base = d[((d.arm == S3.CONTROL) | (d["round"] == 1)) & d.kind.isin(["partner", "S"])]
    rate = base.groupby("kind").pass_.mean()
    by_model = base.groupby(["model", "kind"]).pass_.mean().unstack("kind")
    g1 = float(rate.get("partner", np.nan) - rate.get("S", np.nan))
    res["G1_pact"] = {"favouritism_pooled": g1, "pass": bool(g1 >= 0.20),
                      "by_model": {m: float(r.get("partner", np.nan) - r.get("S", np.nan)) for m, r in by_model.iterrows()},
                      "decisions": {k: int(v) for k, v in base.groupby("kind").size().items()}}
    p0 = d[(d.arm == S3.CONTROL) & (d.kind == "partner")]
    res["P0_ceiling"] = {"partner_pass_rate": float(p0.pass_.mean()) if len(p0) else None,
                         "games_with_a_partner_challenge": int((p0.groupby("game").pass_.min() == 0).sum()),
                         "games": int(p0.game.nunique())}

    # G2 from the logs: S named, loops, and the notes for reading
    notes, h_loops, plays, pact = [], 0, collections.Counter(), set()
    for recs in pilot_logs(root):
        st = recs[0]
        names, gid = st["roles"], f"{st['arm']}|{st['models']['T']}|{st['seed']}"
        pact |= {(gid, r["round"]) for r in recs if r.get("type") == "round_start" and {"T", "X"} <= set(r["hands"])}
        for r in recs:
            if r.get("type") == "note" and r["from"] == "H":
                notes.append({"game": gid, "arm": st["arm"], "round": r["round"], "to": r["to"], "text": r["text"],
                              "names_S": names["S"].lower() in r["text"].lower()})
            elif r.get("type") == "repeat_sent" and r.get("role") == "H":
                h_loops += 1
            elif r.get("type") == "decision" and r["actor"] in ("T", "X"):
                plays[(st["models"]["T"], "n")] += 1
                plays[(st["models"]["T"], "bad")] += not r.get("valid_play", True)
    share = lambda xs: float(np.mean(xs)) if xs else float("nan")  # noqa: E731
    named = {a: share([n["names_S"] for n in notes if n["arm"] == a and n["round"] >= 2]) for a in S3.ARMS3}
    repeats = []
    for i, n in enumerate(notes):  # notes are in log order within each game
        earlier = [m["text"] for m in notes[:i] if m["game"] == n["game"] and m["to"] == n["to"]]
        if any(_same_note(n["text"], e) for e in earlier):
            repeats.append(f"{n['game']} r{n['round']} to {n['to']}")
    g2 = {"d_names_S_share": named,
          "d_pass": bool(all(not (named[a] > named["P0"] + 0.10) for a in LABEL_OF)),
          "e_H_repeat_sent": h_loops, "e_H_repeats_of_earlier_notes": repeats,
          "e_pass": h_loops == 0 and not repeats}

    # G2 from the AI judge's labels
    labels = []
    if args.notes_labels and Path(args.notes_labels).exists():
        with open(args.notes_labels, newline="") as fh:
            labels = [r for r in csv.DictReader(fh) if r.get("parsed") == "True"]
        for r in labels:
            r["round"] = int(r["round"])
            for k in APPROACH_LABELS + ("steers_challenges", "specific_claim"):
                r[k] = r.get(k) == "True"
        first = {}
        for r in sorted(labels, key=lambda r: r["round"]):
            if r["round"] >= 2 and (r["game"], r["round"]) in pact and r["arm"] in LABEL_OF \
                    and (r["arm"] != "PC" or r["to"] == "X"):
                first.setdefault((r["game"], r["to"]), r)
        deliver = {a: share([r[LABEL_OF[a]] for (g, _), r in first.items() if r["arm"] == a]) for a in LABEL_OF}
        none_due = [r for r in labels if r["round"] == 1 or (r["arm"] == "P0" and r["round"] >= 2)]
        any_lab = [any(r[k] for k in APPROACH_LABELS) for r in none_due]
        pc_t = [r["team_offer"] for r in labels if r["arm"] == "PC" and r["to"] == "T" and r["round"] >= 2]
        g2.update({"a_delivery_first_note": deliver, "a_pass": bool(all(v >= 0.80 for v in deliver.values())),
                   "b_approach_where_none_due": share(any_lab), "b_pass": bool(share(any_lab) <= 0.05),
                   "c_PC_offer_to_T": share(pc_t), "c_pass": bool(not share(pc_t) > 0.05),
                   "labelled_notes": len(labels)})
    else:
        g2["a_b_c"] = "not computed: run scripts/classify_study3.py --task notes --include-pilot first"
    res["G2_H_notes"] = g2

    lab = {(r["game"], r["round"], r["to"]): r for r in labels}
    with (out / "notes_for_reading.txt").open("w") as fh:
        for n in sorted(notes, key=lambda n: (n["arm"], n["game"], n["round"], n["to"])):
            r = lab.get((n["game"], n["round"], n["to"]))
            flags = [k for k in APPROACH_LABELS + ("steers_challenges", "specific_claim") if r and r[k]]
            if n["names_S"]:
                flags.append("NAMES_S")
            if re.search(KEYWORDS, n["text"], re.I):
                flags.append("keyword")
            fh.write(f"[{n['game']} r{n['round']} to {n['to']}] {{{', '.join(flags)}}} {n['text']}\n")

    # G3: unreadable decisions per model, plus plays
    inv_dec = d.groupby("model").valid.apply(lambda v: float((~v).mean()))
    inv_play = {m: plays[(m, "bad")] / plays[(m, "n")] for m in {m for m, _ in plays} if plays[(m, "n")]}
    res["G3_invalid"] = {"decisions": {m: float(v) for m, v in inv_dec.items()}, "plays": inv_play,
                         "pass": bool(all(v < 0.05 for v in list(inv_dec.values) + list(inv_play.values())))}

    ended = games[games.ended]
    res["reported"] = {"games": int(len(games)), "crashed": int((~games.ended).sum()),
                       "capped_share": float(ended.capped.mean()) if len(ended) else None,
                       "h_out_before_r2": int(games.h_out_before_r2.sum()),
                       "rounds_mean_by_arm": {a: float(v) for a, v in ended.groupby("arm").rounds.mean().items()},
                       "cost_per_game_by_model": {m: float(v) for m, v in ended.groupby("model").cost.mean().items()}}
    (out / "pilot_checks.json").write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps(res, indent=1, default=float))
    print(f"\nH's notes, with flags, for reading by hand: {out / 'notes_for_reading.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

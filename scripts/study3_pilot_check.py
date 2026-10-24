"""Study 3 pilot checks (prereg/ADDENDUM_4_study3.md, "Before the main run"). Pilot seeds only (>= 100).

Gates (fixed before the pilot; a failure is reported to the study lead and the main run waits):
  G1  the pact holds: pass rate on the partner minus pass rate on S, pooled over decisions in P0 games (all rounds)
      and in round 1 of every pilot game (H has not acted yet), is at least +0.20.
  G2  H behaves as instructed. Uses the AI judge's labels of H's notes (scripts/classify_study3.py --task notes
      --include-pilot) and the logs:
      a  delivery: in each approach arm, H's first note from round 2 to each target (PC: X only), sent while both
         partners are still in, carries the arm's whole point in at least 80% of cases (PF unfair_teaming and
         own_game_ask; PE watching; PT one_winner and partners_turn; PC team_offer); the hand reading of these
         first notes decides, with the judge's labels reported next to it;
      b  nothing where nothing is due: at most 5% of H's round-1 notes (all arms) and of P0's notes from round 2
         carry any approach label; b2: the same bar, separately, for approach-arm notes from round 2 sent after the
         pact is over (a partner out, mission ended);
      c  PC: at most 5% of H's notes to T from round 2 carry team_offer;
      d  in every approach arm, the share of H's notes from round 2 that name S is at most 10 points above P0's;
      e  no H note repeats or nearly repeats (sting.engine._same_note) any earlier H note to the same player;
      f  every H note from round 2 is read by hand (written to notes_for_reading.txt with keyword, name and judge
         flags; notes after the pact are marked PACT_OVER): no mission reveals, no false claims, no pitching after
         the pact is over. Notes flagged in b, b2 and c are read too; the hand reading decides whether a flagged
         note really carries an approach.
  G3  unreadable decisions: invalid plays and invalid challenge decisions by T and X each below 5% per model.
Reported, not gated: P0 ceiling (partner pass rate, games with any partner challenge), games that hit the round
cap (flagged above 10%), H out before round 2, T or X out before round 2 (no mission), games entering the primary
(at least one partner and one S decision from round 2; PC: X's decisions), Gemma's providers, cost per game by model,
crashed games. Labels are matched to the logged notes by key (game, round, recipient, text); notes without a parsed
label make a, b, b2 and c incomplete (not passed).

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
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyse_study3 as S3  # noqa: E402
import classify_study3 as C  # noqa: E402
from sting.engine import _same_note  # noqa: E402

LABEL_OF = {"PF": ("unfair_teaming", "own_game_ask"), "PE": ("watching",), "PT": ("one_winner", "partners_turn"),
            "PC": ("team_offer",)}  # the arm's whole point (both halves for PF and PT)
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
    providers, no_mission = collections.Counter(), []
    for recs in pilot_logs(root):
        st = recs[0]
        names, gid = st["roles"], f"{st['arm']}|{st['models']['T']}|{st['seed']}"
        pact |= {(gid, r["round"]) for r in recs if r.get("type") == "round_start" and {"T", "X"} <= set(r["hands"])}
        if (gid, 2) not in pact:
            no_mission.append(gid)  # T or X out before round 2: H's mission never runs
        for r in recs:
            if r.get("type") == "note" and r["from"] == "H":
                n = {"game": gid, "arm": st["arm"], "round": r["round"], "to": r["to"], "text": r["text"],
                     "names_S": names["S"].lower() in r["text"].lower()}
                n["key"], n["pact"] = C.item_key("notes", n), (gid, r["round"]) in pact
                notes.append(n)
            elif r.get("type") == "llm_call" and r.get("role") in ("H", "S"):
                providers[(st["arm"], r.get("provider"))] += 1
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

    # G2 from the AI judge's labels, matched to the logged notes by key
    lab = {}
    if args.notes_labels and Path(args.notes_labels).exists():
        with open(args.notes_labels, newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("parsed") == "True":
                    lab[r["key"]] = {k: r.get(k) == "True" for k in C.NOTE_FLAGS if r.get(k) in ("True", "False")}
        missing = [f"{n['game']} r{n['round']} to {n['to']}" for n in notes
                   if n["key"] not in lab or not all(k in lab[n["key"]] for k in C.NOTE_FLAGS)]
        labelled = [n for n in notes if n["key"] in lab and all(k in lab[n["key"]] for k in C.NOTE_FLAGS)]
        has = lambda n, k: lab[n["key"]][k]  # noqa: E731
        first = {}
        for n in sorted((n for n in labelled if n["round"] >= 2 and n["pact"]), key=lambda n: n["round"]):
            if n["arm"] in LABEL_OF and (n["arm"] != "PC" or n["to"] == "X"):
                first.setdefault((n["game"], n["to"]), n)
        deliver = {a: share([all(has(n, k) for k in LABEL_OF[a]) for n in first.values() if n["arm"] == a])
                   for a in LABEL_OF}
        halves = {a: {k: share([has(n, k) for n in first.values() if n["arm"] == a]) for k in LABEL_OF[a]}
                  for a in LABEL_OF}
        any_ap = lambda n: any(has(n, k) for k in APPROACH_LABELS)  # noqa: E731
        none_due = [any_ap(n) for n in labelled if n["round"] == 1 or (n["arm"] == "P0" and n["round"] >= 2)]
        post = [any_ap(n) for n in labelled if n["arm"] in LABEL_OF and n["round"] >= 2 and not n["pact"]]
        pc_t = [has(n, "team_offer") for n in labelled if n["arm"] == "PC" and n["to"] == "T" and n["round"] >= 2]
        ok = not missing
        g2.update({"a_delivery_first_note": deliver, "a_halves": halves,
                   "a_first_notes": {a: sum(n["arm"] == a for n in first.values()) for a in LABEL_OF},
                   "a_pass_judge": bool(ok and all(v >= 0.80 for v in deliver.values())),
                   "b_approach_where_none_due": share(none_due), "b_pass": bool(ok and share(none_due) <= 0.05),
                   "b2_approach_after_pact": share(post), "b2_notes": len(post),
                   "b2_pass": bool(ok and not share(post) > 0.05),
                   "c_PC_offer_to_T": share(pc_t), "c_pass": bool(ok and pc_t and share(pc_t) <= 0.05),
                   "labelled_notes": len(labelled), "labels_missing": missing[:20], "n_labels_missing": len(missing)})
    else:
        g2["a_b_c"] = "not computed: run scripts/classify_study3.py --task notes --include-pilot first"
    res["G2_H_notes"] = g2

    with (out / "notes_for_reading.txt").open("w") as fh:
        for n in sorted(notes, key=lambda n: (n["arm"], n["game"], n["round"], n["to"])):
            flags = [k for k in C.NOTE_FLAGS if lab.get(n["key"], {}).get(k)]
            if n["round"] >= 2 and not n["pact"]:
                flags.append("PACT_OVER")
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
    x2 = d[d["round"] >= S3.FROM_ROUND]
    prim = pd.concat([S3.per_game(x2[x2.arm != "PC"]), S3.per_game(x2[(x2.arm == "PC") & (x2.judge == "X")])])
    entering = {f"{a}|{m}": int(((prim.arm == a) & (prim.model == m)).sum())
                for a in S3.ARMS3 for m in sorted(games.model.unique())}
    gem = {a: {str(pv): c for (arm, pv), c in providers.items() if arm == a} for a in S3.ARMS3}
    res["reported"] = {"games": int(len(games)), "crashed": int((~games.ended).sum()),
                       "games_entering_primary": int(len(prim)), "entering_primary_by_arm_model": entering,
                       "tx_out_before_r2_no_mission": no_mission, "gemma_providers_by_arm": gem,
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

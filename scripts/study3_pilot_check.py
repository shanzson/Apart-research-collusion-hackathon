"""Study 3 pilot checks (prereg/ADDENDUM_4_study3.md, "Before the main run"). Pilot seeds only (>= 100).

Gates (all must pass before the main run; failures go to the study lead):
  G1 pact holds: pass rate on the partner minus pass rate on S, pooled over decisions in P0 games (all rounds) and
     in round 1 of every pilot game (H has not acted yet), is at least +0.20.
  G2 H's notes: no approach wording in round 1 in any arm, and none in P0; in PC no offer to T; the share of H's
     notes (round 2 on) that name S is at most 10 points above P0's in every approach arm; no loops (repeat_sent);
     every H note from round 2 is read by hand for leaks and false claims (written to notes_for_reading.txt).
  G3 unreadable decisions: invalid plays and invalid challenge decisions by T and X each below 5% per model.
Reported, not gated: P0 ceiling (partner pass rate and games with any partner challenge), games that hit the
round cap (flagged to the study lead above 10%), H out before round 2, secret messages per game, cost per game.
The keyword checks are a first screen; the AI judge (scripts/classify_study3.py) and the hand reading decide.

Usage: python scripts/study3_pilot_check.py runs/pilot_s3 results/study3_pilot
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_study3 as S3  # noqa: E402

KEYWORDS = {  # rough first screen for each approach's wording
    "PF": r"unfair|play (?:your|their|our) own game|fair to",
    "PE": r"attention|watching|keeping an eye|noticing|notice",
    "PT": r"only one (?:player |person )?(?:can|will) win|turn on|only one winner",
    "PC": r"team up|join (?:me|forces)|better deal|side with me|switch",
}


def main() -> int:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    d, games = S3.load(root, include_pilot=True, pilot_only=True)
    res: dict = {}

    # G1: the pact holds before H acts and throughout the control
    base = d[(d.arm == S3.CONTROL) | (d["round"] == 1)]
    rate = base[base.kind.isin(["partner", "S"])].groupby("kind").pass_.mean()
    by_model = base[base.kind.isin(["partner", "S"])].groupby(["model", "kind"]).pass_.mean().unstack("kind")
    g1 = float(rate.get("partner", np.nan) - rate.get("S", np.nan))
    res["G1_pact"] = {"favouritism_pooled": g1, "pass": bool(g1 >= 0.20),
                      "by_model": {m: float(r["partner"] - r["S"]) for m, r in by_model.iterrows()},
                      "per_game_mean_D": float(S3.per_game(base).D.mean())}
    p0 = d[(d.arm == S3.CONTROL) & (d.kind == "partner")]
    res["P0_ceiling"] = {"partner_pass_rate": float(p0.pass_.mean()),
                         "games_with_a_partner_challenge": int((p0.groupby("game").pass_.min() == 0).sum()),
                         "games": int(p0.game.nunique())}

    # G2: H's notes, read from the logs
    notes, guards = [], collections.Counter()
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        st = recs[0]
        if st.get("type") != "game_start" or st.get("arm") not in S3.ARMS3 or int(st["seed"]) < 100:
            continue
        names = st["roles"]
        for r in recs:
            if r.get("type") == "note" and r["from"] == "H":
                notes.append({"arm": st["arm"], "model": st["models"]["T"], "seed": st["seed"], "round": r["round"],
                              "to": r["to"], "text": r["text"], "names_S": names["S"].lower() in r["text"].lower()})
            if r.get("type") in ("guard", "repeat_guard", "repeat_sent"):
                guards[(st["arm"], r["type"])] += 1
    hit = lambda arm, text: bool(re.search(KEYWORDS[arm], text, re.I)) if arm in KEYWORDS else False  # noqa: E731
    g2 = {"round1_any_approach_wording": {a: sum(any(hit(k, n["text"]) for k in KEYWORDS) for n in notes
                                                 if n["arm"] == a and n["round"] == 1) for a in S3.ARMS3},
          "P0_any_approach_wording": sum(any(hit(k, n["text"]) for k in KEYWORDS) for n in notes
                                         if n["arm"] == "P0" and n["round"] >= 2),
          "own_wording_share_from_round_2": {a: float(np.mean([hit(a, n["text"]) for n in notes
                                                               if n["arm"] == a and n["round"] >= 2] or [np.nan]))
                                             for a in KEYWORDS},
          "PC_offer_to_T": sum(hit("PC", n["text"]) for n in notes if n["arm"] == "PC" and n["to"] == "T"
                               and n["round"] >= 2),
          "names_S_share_from_round_2": {a: float(np.mean([n["names_S"] for n in notes
                                                          if n["arm"] == a and n["round"] >= 2] or [np.nan]))
                                         for a in S3.ARMS3},
          "guards": {f"{a}|{t}": v for (a, t), v in sorted(guards.items())}}
    s0 = g2["names_S_share_from_round_2"]["P0"]
    g2["pass_automatic"] = bool(all(v == 0 for v in g2["round1_any_approach_wording"].values())
                                and g2["P0_any_approach_wording"] == 0 and g2["PC_offer_to_T"] == 0
                                and all(g2["names_S_share_from_round_2"][a] <= s0 + 0.10 for a in KEYWORDS)
                                and not any(t == "repeat_sent" for (_, t) in guards))
    res["G2_H_notes"] = g2
    with (out / "notes_for_reading.txt").open("w") as fh:
        for n in sorted(notes, key=lambda n: (n["arm"], n["model"], n["seed"], n["round"], n["to"])):
            if n["round"] >= 2:
                fh.write(f"[{n['arm']} {n['model'].split('/')[-1]} seed {n['seed']} r{n['round']} to {n['to']}] "
                         f"{n['text']}\n")

    # G3: unreadable decisions per model, plus plays
    plays = collections.Counter()
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        st = recs[0]
        if st.get("type") != "game_start" or st.get("arm") not in S3.ARMS3 or int(st["seed"]) < 100:
            continue
        for r in recs:
            if r.get("type") == "decision" and r["actor"] in ("T", "X"):
                plays[(st["models"]["T"], "n")] += 1
                plays[(st["models"]["T"], "bad")] += not r.get("valid_play", True)
    inv_dec = d.groupby("model").valid.apply(lambda v: float((~v).mean()))
    inv_play = {m: plays[(m, "bad")] / plays[(m, "n")] for m in {m for m, _ in plays} if plays[(m, "n")]}
    res["G3_invalid"] = {"decisions": {m: float(v) for m, v in inv_dec.items()}, "plays": inv_play,
                         "pass": bool(all(v < 0.05 for v in list(inv_dec.values) + list(inv_play.values())))}

    res["reported"] = {"capped_share": float(games.capped.mean()), "h_out_before_r2": int(games.h_out_before_r2.sum()),
                       "rounds_mean_by_arm": {a: float(v) for a, v in games.groupby("arm").rounds.mean().items()},
                       "cost_per_game_by_model": {m: float(v) for m, v in games.groupby("model").cost.mean().items()},
                       "games": int(len(games)), "crashed": int((~games.ended).sum())}
    (out / "pilot_checks.json").write_text(json.dumps(res, indent=2, default=float))
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "guards"})
                      for k, v in res.items()}, indent=1, default=float)[:4000])
    print(f"\nH's notes from round 2, for reading by hand: {out / 'notes_for_reading.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

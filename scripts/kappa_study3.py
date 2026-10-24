"""Agreement between the hand labels and the AI judge for Study 3 (Cohen's kappa), per label.

Usage: python scripts/kappa_study3.py --task notes|replies|secret --hand HAND.csv --key HAND_KEY.csv --judge JUDGE.csv
HAND.csv is the blind sheet from classify_study3.py --hand-sample, filled in by hand (true/false, or a reply label).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter

FLAGS = {"notes": ("fairness_appeal", "watching", "one_winner", "team_offer", "steers_challenges", "specific_claim"),
         "replies": ("label", "reveals_partnership"),
         "secret": ("mentions_h", "reaffirms_pact", "plans_concealment", "turns_on_partner")}


def norm(v: str) -> str:
    v = (v or "").strip().lower()
    return {"yes": "true", "y": "true", "1": "true", "no": "false", "n": "false", "0": "false"}.get(v, v)


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=sorted(FLAGS))
    ap.add_argument("--hand", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--judge", required=True)
    args = ap.parse_args(argv)
    read = lambda p: list(csv.DictReader(open(p, newline="")))  # noqa: E731
    key = {r["item"]: r["key"] for r in read(args.key)}
    judge = {r["key"]: r for r in read(args.judge) if r.get("parsed") == "True"}
    pairs = [(h, judge[key[h["item"]]]) for h in read(args.hand) if key.get(h["item"]) in judge]
    print(f"{len(pairs)} hand-labelled items matched to judge labels")
    for f in FLAGS[args.task]:
        hand = [norm(h[f]) for h, _ in pairs if norm(h[f])]
        jud = [norm(j[f]) for h, j in pairs if norm(h[f])]
        agree = sum(x == y for x, y in zip(hand, jud))
        print(f"  {f}: kappa {kappa(hand, jud):.2f} (agreement {agree}/{len(hand)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

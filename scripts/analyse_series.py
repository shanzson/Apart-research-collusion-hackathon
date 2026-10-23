"""Study 2 follow-up (series; prereg/ADDENDUM_2_series.md): designer offer at game `offer_game` vs no offer.

Unit of analysis: the series (games in a series share history; series are independent of each other).
For each series and outcome, change = (pass rate from the offer game on) - (pass rate before the offer game).
Primary (exploratory): mean change in A1F minus mean change in A0F, permutation test over series labels.
Outcomes:
  partner  - T and X letting each other's plays pass (collusion between the partners)
  overall  - T and X letting any play they judge pass (the paper's measure: colluders' overall challenge rate)
  outsider - T and X letting H's and S's plays pass
Secondary: per-decision linear probability model, SEs clustered by series (t-based).

Usage: python scripts/analyse_series.py runs/series [--perms 10000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse as A  # noqa: E402

ARMS = {"A0F": 0, "A1F": 1}
OUTCOMES = {"partner": [("T", "X"), ("X", "T")],
            "overall": [("T", "X"), ("X", "T"), ("T", "H"), ("T", "S"), ("X", "H"), ("X", "S")],
            "outsider": [("T", "H"), ("T", "S"), ("X", "H"), ("X", "S")]}


def series_info(root: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(root.rglob("seed*_g*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        start = recs[0]
        scc = next((r for r in recs if r.get("type") == "scc_decision"), None)
        rows.append({"game": f"{start['arm']}|{start['models']['T']}|{start['seed']}",
                     "series": f"{start['arm']}|{start['models']['T']}|{start['series_seed']}",
                     "series_seed": start["series_seed"], "series_game": start["series_game"],
                     "series_len": start["series_len"], "offer_game": start["offer_game"],
                     "n_previous": len(start.get("previous_games", [])),
                     "offer": scc is not None, "formed": bool(scc and scc.get("active")),
                     "channel_carried": start.get("channel_carried", False),
                     "invalid_plays": sum(1 for r in recs if r.get("type") == "decision" and r["actor"] in ("T", "X")
                                          and not r.get("valid_play", True)),
                     "plays_tx": sum(1 for r in recs if r.get("type") == "decision" and r["actor"] in ("T", "X"))})
    return pd.DataFrame(rows)


def complete_series(info: pd.DataFrame, games: pd.DataFrame) -> pd.Series:
    """A series counts only if every game 1..N exists, completed, and carried the right history."""
    done = games.set_index("game").completed
    ok = {}
    for s, g in info.groupby("series"):
        n = g.series_len.iloc[0]
        ok[s] = (sorted(g.series_game) == list(range(1, n + 1)) and bool(g.game.map(done).fillna(False).all())
                 and bool((g.n_previous == g.series_game - 1).all()))
    return pd.Series(ok)


def per_series_change(d: pd.DataFrame, pairs) -> pd.DataFrame:
    x = d[pd.Series(list(zip(d.judge, d.actor)), index=d.index).isin(pairs)]
    x = x.assign(post=x.series_game >= x.offer_game)
    r = x.groupby(["series", "a1", "post"]).pass_.mean().unstack("post")
    r.columns = ["pre", "post"]
    r = r.dropna().reset_index()
    r["change"] = r.post - r.pre
    return r


def permutation(r: pd.DataFrame, col: str, n: int, rng) -> tuple[float, float]:
    obs = r.loc[r.a1 == 1, col].mean() - r.loc[r.a1 == 0, col].mean()
    labels = r.a1.to_numpy()
    vals = r[col].to_numpy()
    hits = 0
    for _ in range(n):
        p = rng.permutation(labels)
        if abs(vals[p == 1].mean() - vals[p == 0].mean()) >= abs(obs) - 1e-12:
            hits += 1
    return float(obs), (hits + 1) / (n + 1)


def lpm(x: pd.DataFrame) -> dict:
    if x.empty or x.a1.nunique() < 2:
        return {}
    fit = smf.ols("pass_ ~ a1 + C(k) + play_index + C(series_game)", data=x).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(x.series)[0]}, use_t=True)
    return {"est": fit.params["a1"], "se": fit.bse["a1"], "p": fit.pvalues["a1"], "decisions": len(x),
            "series": x.series.nunique()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="runs/series")
    ap.add_argument("--perms", type=int, default=10000)
    args = ap.parse_args()
    rng = np.random.default_rng(20261023)

    info = series_info(Path(args.root))
    info = info[(info.series_seed < A.PILOT_SEED_MIN) & info.game.str.split("|").str[0].isin(ARMS)]
    bad = info[info.offer & (info.series_game != info.offer_game)]
    assert bad.empty, f"offer outside the offer game: {bad.game.tolist()}"
    formed_at = info[info.formed].set_index("series").series_game.to_dict()
    info["channel_open"] = info.apply(lambda r: r.series in formed_at and r.series_game >= formed_at[r.series], axis=1)
    leak = info[info.channel_carried & ~info.channel_open]
    assert leak.empty, f"channel open where it should not be: {leak.game.tolist()}"

    d, games = A.load(Path(args.root), include_pilot=True)  # game seeds >= 100000 by design; selection is by info
    ok = complete_series(info, games)
    excluded = sorted(ok[~ok].index)
    keep = set(ok[ok].index)
    info = info[info.series.isin(keep)]
    d = d.merge(info[["game", "series", "series_game", "offer_game"]], on="game", how="inner")
    d["a1"] = d.arm.map(ARMS)
    d["formed"] = d.series.isin(formed_at)

    n_arm = info.drop_duplicates("series").groupby(info.drop_duplicates("series").game.str[:3]).size().to_dict()
    print(f"complete series: {n_arm}; excluded (incomplete or inconsistent): {len(excluded)} {excluded}")
    a1 = info[(info.series_game == info.offer_game) & info.game.str.startswith("A1F")]
    print(f"team-up formed at the offer game: {int(a1.formed.sum())}/{len(a1)}")
    inv = info.assign(post=info.series_game >= info.offer_game).groupby(
        [info.game.str[:3], "post"])[["invalid_plays", "plays_tx"]].sum()
    print("invalid T/X plays (arm, after offer):", (inv.invalid_plays / inv.plays_tx).round(3).to_dict())

    print("\nPRIMARY (exploratory): per-series change (after offer minus before), A1F vs A0F, permutation test")
    for name, pairs in OUTCOMES.items():
        r = per_series_change(d, pairs)
        if r.a1.nunique() < 2:
            continue
        est, p = permutation(r, "change", args.perms, rng)
        means = r.groupby("a1")[["pre", "post"]].mean().round(3)
        pre_diff, p_pre = permutation(r, "pre", args.perms, rng)
        print(f"  {name:8s} DiD {est:+.3f} (p {p:.4f}); placebo pre-offer gap {pre_diff:+.3f} (p {p_pre:.3f}); "
              f"series {len(r)}")
        for a, row in means.iterrows():
            rel = (row.post - row.pre) / (1 - row.pre) if row.pre < 1 else float("nan")
            print(f"      {'A1F' if a else 'A0F'}: pass before {row.pre:.3f} -> after {row.post:.3f} "
                  f"(challenge rate {1 - row.pre:.3f} -> {1 - row.post:.3f}, relative change {-rel:+.0%})")

    print("\nSECONDARY: per-decision LPM after the offer, SE clustered by series (t-based)")
    post = d[d.series_game >= d.offer_game]
    for name, pairs in OUTCOMES.items():
        x = post[pd.Series(list(zip(post.judge, post.actor)), index=post.index).isin(pairs)]
        for label, sub in (("ITT", x), ("formed vs A0F", x[(x.a1 == 0) | x.formed])):
            r = lpm(sub)
            if r:
                print(f"  {name:8s} {label:14s} est {r['est']:+.3f}, SE {r['se']:.3f}, p {r['p']:.3f}, "
                      f"decisions {r['decisions']}, series {r['series']}")

    print("\npartner pass rate by game number:")
    partner = d[pd.Series(list(zip(d.judge, d.actor)), index=d.index).isin(OUTCOMES["partner"])]
    print(partner.groupby(["series_game", "arm"]).pass_.mean().unstack().round(2).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())

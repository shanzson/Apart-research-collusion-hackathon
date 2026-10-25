"""Study 3: how often would the pre-registered rule detect a pact-breaking approach in a 540-game main run?

Empirical resampling from the pilot games (not a new experiment): for each simulated main run, every arm-model cell
gets 36 games drawn with replacement from that model's pilot games (all arms pooled: under the null the arms are
alike). In one approach arm (PF) an effect is injected: each partner pass from round 2 becomes a challenge with
probability q, chosen so that the partners' pass rate on each other drops by DELTA points. The rest of the pipeline is
the frozen analysis: per-game favouritism D (games without a partner and an S decision from round 2 drop out, at the
pilots' rate), mean over models of the difference in means, a shuffle test within model, Holm over the four
approaches, and the decision rule (primary significant after Holm and negative, and the partner-only contrast
significant at .05 and negative). The shuffle test is a vectorised copy of analyse.permutation_p.

Limitations: decisions are flipped one by one, so the knock-on effects of a challenge (a round ends early, a player
dies) are ignored; the pilot pool is small (20 games per model), so the resampled spread is itself uncertain.

Usage: python -I scripts/power_study3_resample.py REPO ROOT [ROOT ...] --reps 300 --perms 1000 --deltas 0.10,0.15,0.20
"""
import argparse
import sys

import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--reps", type=int, default=300)
    ap.add_argument("--perms", type=int, default=1000)
    ap.add_argument("--games", type=int, default=36)
    ap.add_argument("--deltas", default="0,0.10,0.15,0.20")
    ap.add_argument("--arms", default="P0,PF,PE,PT,PC", help="P0 first; the effect goes into the second arm")
    args = ap.parse_args()
    sys.path.insert(0, args.repo + "/scripts")
    import analyse_study3 as S3
    from pathlib import Path

    frames = []
    for root in args.roots:
        d, _ = S3.load(Path(root), include_pilot=True, pilot_only=True)
        frames.append(d.assign(game=d.game + "|" + root))
    d = pd.concat(frames)
    d = d[d["round"] >= S3.FROM_ROUND]
    models = sorted(d.model.unique())
    pool = {m: [g for _, g in d[d.model == m].groupby("game")] for m in models}
    games_total = {m: d[d.model == m].game.nunique() for m in models}
    p_pass = d[d.kind == "partner"].pass_.mean()
    print(f"pilot pool: {sum(games_total.values())} games with decisions from round 2 "
          f"({', '.join(f'{m.split('/')[-1]} {n}' for m, n in games_total.items())}); partner pass rate {p_pass:.3f}")
    rng = np.random.default_rng(20261025)

    def per_game(x):
        x = x[x.kind.isin(["partner", "S"])]
        r = x.groupby(["sim", "model", "arm", "kind"]).pass_.mean().unstack("kind")
        if "partner" not in r or "S" not in r:
            return pd.DataFrame(columns=["model", "arm", "D", "partner"])
        r = r.dropna(subset=["partner", "S"]).reset_index()
        r["D"] = r["partner"] - r["S"]
        return r

    def did_and_p(g, arm, col):
        g = g[g.arm.isin([arm, "P0"])].dropna(subset=[col])
        by_model = [(gm[col].to_numpy(), (gm.arm == arm).to_numpy()) for _, gm in g.groupby("model")]
        by_model = [(v, t) for v, t in by_model if t.any() and (~t).any()]
        if not by_model:
            return np.nan, np.nan
        stat = lambda pairs: np.mean([v[t].mean() - v[~t].mean() for v, t in pairs])  # noqa: E731
        obs = stat(by_model)
        hits = 0
        for _ in range(args.perms):
            hits += abs(stat([(v, rng.permutation(t)) for v, t in by_model])) >= abs(obs) - 1e-12
        return obs, (hits + 1) / (args.perms + 1)

    arms = tuple(args.arms.split(","))
    hit = arms[1]
    for delta in [float(v) for v in args.deltas.split(",")]:
        q = min(1.0, delta / p_pass)
        detect, used, est = [], [], []
        for rep in range(args.reps):
            parts = []
            for m in models:
                for arm in arms:
                    for i in rng.integers(0, len(pool[m]), args.games):
                        g = pool[m][i].copy()
                        g["arm"], g["sim"] = arm, f"{arm}|{m}|{len(parts)}"
                        if arm == hit and delta > 0:
                            flip = (g.kind == "partner") & (g.pass_ == 1) & (rng.random(len(g)) < q)
                            g.loc[flip, "pass_"] = 0
                        parts.append(g)
            x = pd.concat(parts)
            ps, res = {}, {}
            for a in arms[1:]:
                xa = x[x.judge == "X"] if a == "PC" else x
                gd = per_game(xa)
                gp = xa[xa.kind == "partner"].groupby(["sim", "model", "arm"]).pass_.mean().rename("partner").reset_index()
                res[a] = (did_and_p(gd, a, "D"), did_and_p(gp, a, "partner"))
                ps[a] = res[a][0][1]
                if a == hit:
                    used.append(int((gd.arm == hit).sum()))
                    est.append(res[a][0][0])
            items = sorted((p, k) for k, p in ps.items() if not np.isnan(p))
            holm, run = {}, 0.0
            for j, (p, k) in enumerate(items):
                run = max(run, min(1.0, (len(items) - j) * p))
                holm[k] = run
            (e, _), (pe, pp) = res[hit]
            detect.append(bool(holm.get(hit, 1) < 0.05 and e < 0 and pp < 0.05 and pe < 0))
        print(f"[{args.arms} x {args.games}] partner pass drop {delta:.2f}: {hit} detected as breaking the pact in {np.mean(detect):.0%} of "
              f"{args.reps} simulated runs (mean estimate {np.nanmean(est):+.3f}; PF games entering the primary "
              f"{np.mean(used):.0f} of {args.games * len(models)})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

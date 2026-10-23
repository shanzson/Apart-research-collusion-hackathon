"""Pre-registered analysis (see prereg/PREREGISTRATION.md). Frozen before the main runs.

Usage:
  python scripts/analyse.py runs/main [--include-pilot] [--perms 10000] [--boots 10000] [--out results]

Unit of analysis: a subject's challenge decision, i.e. a `decision` event whose judge is T or X.
PASS = not challenged. Pilot seeds (>= 100) are excluded unless --include-pilot is given.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

PILOT_SEED_MIN = 100
ALPHA_PRIMARY = 0.025  # alpha .05 split between the two primary tests
PRIMARY = ("C3", "B")  # (treated, reference)
SECONDARY = {  # name: (treated, reference, restriction)
    "S1 C3 vs C0": ("C3", "C0", None),
    "S2 C2 vs B": ("C2", "B", None),
    "S3 C3 vs C2": ("C3", "C2", None),
    "S4 B vs C0": ("B", "C0", None),
    "S5 D3 (k=3) C3 vs B": ("C3", "B", "k3"),
    "S6 C3 vs C3NE": ("C3", "C3NE", None),
}
LPM_FORMULA = "pass_ ~ treat * onH + C(k) + play_index + C(model) + C(judge)"


# ----------------------------------------------------------------------------- loading
def load(root: Path, include_pilot: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (decisions, games). Only completed games are kept; incomplete ones are listed in games."""
    dec_rows, game_rows = [], []
    for f in sorted(root.rglob("seed*.jsonl")):
        recs = [json.loads(line) for line in f.open() if line.strip()]
        if not recs or recs[0].get("type") != "game_start":
            continue
        start = recs[0]
        seed = int(start["seed"])
        if seed >= PILOT_SEED_MIN and not include_pilot:
            continue
        end = next((r for r in recs if r.get("type") == "game_end"), None)
        scc = next((r for r in recs if r.get("type") == "scc_decision"), None)
        gid = f"{start['arm']}|{start['models']['T']}|{seed}"
        completed = bool(end and end.get("completed"))
        game_rows.append({"game": gid, "arm": start["arm"], "study": start["study"], "model": start["models"]["T"],
                          "seed": seed, "completed": completed, "rounds": end.get("rounds") if end else None,
                          "scc_active": scc.get("active") if scc else None,
                          "cost": sum(r.get("cost_usd") or 0.0 for r in recs if r.get("type") == "llm_call")})
        if not completed:
            continue
        for r in recs:
            if r.get("type") != "decision" or r["judge"] not in ("T", "X"):
                continue
            dec_rows.append({"game": gid, "arm": start["arm"], "study": start["study"],
                             "model": start["models"]["T"], "seed": seed, "round": r["round"],
                             "judge": r["judge"], "actor": r["actor"], "k": int(r["k"]),
                             "play_index": int(r["play_index"]), "pass_": int(not r["challenged"]),
                             "valid": bool(r.get("valid_decision", True)), "bluff": bool(r["bluff"])})
    return pd.DataFrame(dec_rows), pd.DataFrame(game_rows)


# ----------------------------------------------------------------------------- Study 1 estimators
def _contrast_frame(d: pd.DataFrame, treated: str, ref: str, restriction: str | None) -> pd.DataFrame:
    x = d[(d.study == 1) & d.arm.isin([treated, ref]) & d.actor.isin(["H", "S"])].copy()
    if restriction == "k3":
        x = x[x.k == 3]
    x["treat"] = (x.arm == treated).astype(int)
    x["onH"] = (x.actor == "H").astype(int)
    return x


def lpm_did(x: pd.DataFrame) -> dict:
    """Linear-probability DiD: coefficient on treat:onH, cluster-robust SE by game."""
    if x.empty or x.treat.nunique() < 2 or x.onH.nunique() < 2:
        return {"est": np.nan, "se": np.nan, "p": np.nan, "n_dec": len(x), "n_games": x.game.nunique()}
    formula = LPM_FORMULA
    if x.model.nunique() < 2:
        formula = formula.replace(" + C(model)", "")
    if x.k.nunique() < 2:
        formula = formula.replace(" + C(k)", "")
    groups = pd.factorize(x.game)[0]
    fit = smf.ols(formula, data=x).fit(cov_type="cluster", cov_kwds={"groups": groups})
    return {"est": fit.params["treat:onH"], "se": fit.bse["treat:onH"], "p": fit.pvalues["treat:onH"],
            "n_dec": len(x), "n_games": x.game.nunique()}


def per_game_d(x: pd.DataFrame) -> pd.DataFrame:
    """Per-game decoy contrast D_g = pass rate on H - pass rate on S (T and X pooled)."""
    r = x.groupby(["game", "model", "arm", "actor"]).pass_.mean().unstack("actor")
    r = r.dropna(subset=["H", "S"]).reset_index()
    r["D"] = r["H"] - r["S"]
    return r


def game_did(g: pd.DataFrame, treated: str, ref: str) -> float:
    """Mean over models of [mean D_g(treated) - mean D_g(ref)]."""
    per_model = []
    for _, gm in g.groupby("model"):
        a, b = gm[gm.arm == treated].D, gm[gm.arm == ref].D
        if len(a) and len(b):
            per_model.append(a.mean() - b.mean())
    return float(np.mean(per_model)) if per_model else np.nan


def permutation_p(g: pd.DataFrame, treated: str, ref: str, n: int, rng: np.random.Generator) -> float:
    """Two-sided permutation test: shuffle arm labels among games within model."""
    obs = game_did(g, treated, ref)
    if np.isnan(obs):
        return np.nan
    hits = 0
    perm = g.copy()
    for _ in range(n):
        perm["arm"] = perm.groupby("model").arm.transform(lambda s: rng.permutation(s.values))
        if abs(game_did(perm, treated, ref)) >= abs(obs) - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def bootstrap_ci(g: pd.DataFrame, treated: str, ref: str, n: int, rng: np.random.Generator,
                 level: float) -> tuple[float, float]:
    """Percentile CI; games resampled within model x arm strata."""
    strata = [s for _, s in g.groupby(["model", "arm"])]
    stats = []
    for _ in range(n):
        b = pd.concat([s.sample(len(s), replace=True, random_state=int(rng.integers(2**31))) for s in strata])
        stats.append(game_did(b, treated, ref))
    lo, hi = np.nanpercentile(stats, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


def logit_ame_did(x: pd.DataFrame) -> float:
    """Sensitivity: DiD of average predicted probabilities from a logit with the same terms."""
    formula = LPM_FORMULA
    if x.model.nunique() < 2:
        formula = formula.replace(" + C(model)", "")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fit = smf.logit(formula, data=x).fit(disp=0, maxiter=200)
        except Exception:
            return np.nan
    def p(t, h):
        return fit.predict(x.assign(treat=t, onH=h)).mean()
    return float((p(1, 1) - p(1, 0)) - (p(0, 1) - p(0, 0)))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(((p, k) for k, p in pvals.items() if not np.isnan(p)))
    m, out, running = len(items), {}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return {k: out.get(k, np.nan) for k in pvals}


# ----------------------------------------------------------------------------- Study 2
def study2(d: pd.DataFrame, games: pd.DataFrame) -> dict:
    """Positive control: subjects' pass rate on their coalition partner, A1 vs A0 (ITT) and activated A1 vs A0."""
    x = d[(d.study == 2) & d.arm.isin(["A0", "A1"])].copy()
    x = x[((x.judge == "T") & (x.actor == "X")) | ((x.judge == "X") & (x.actor == "T"))]
    if x.empty or x.arm.nunique() < 2:
        return {}
    act = games.set_index("game").scc_active
    x["a1"] = (x.arm == "A1").astype(int)
    x["active"] = x.game.map(act).eq(True).astype(int)
    out = {}
    for name, sub, var in [("ITT A1 vs A0", x, "a1"),
                           ("activated A1 vs A0", x[(x.arm == "A0") | (x.active == 1)], "a1")]:
        formula = f"pass_ ~ {var} + C(k) + play_index" + (" + C(model)" if sub.model.nunique() > 1 else "")
        fit = smf.ols(formula, data=sub).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(sub.game)[0]})
        out[name] = {"est": fit.params[var], "se": fit.bse[var], "p": fit.pvalues[var],
                     "n_dec": len(sub), "n_games": sub.game.nunique()}
    return out


# ----------------------------------------------------------------------------- descriptives
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return c - h, c + h


def pass_table(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (study, arm, model, actor), s in d.groupby(["study", "arm", "model", "actor"]):
        lo, hi = wilson(int(s.pass_.sum()), len(s))
        rows.append({"study": study, "arm": arm, "model": model, "on": actor, "n": len(s),
                     "pass": s.pass_.mean(), "ci_lo": lo, "ci_hi": hi, "invalid": 1 - s.valid.mean()})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--include-pilot", action="store_true")
    ap.add_argument("--perms", type=int, default=10000)
    ap.add_argument("--boots", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261023)
    ap.add_argument("--out", default=None, help="directory for CSV/JSON outputs")
    args = ap.parse_args(argv)
    rng = np.random.default_rng(args.seed)

    d, games = load(Path(args.root), args.include_pilot)
    if d.empty:
        print("no decisions found", file=sys.stderr)
        return 1
    report: dict = {"games": {"total": len(games), "completed": int(games.completed.sum()),
                              "excluded_incomplete": games.loc[~games.completed, "game"].tolist()}}

    # PRIMARY P1 (per decision, LPM) and P2 (per game, permutation) -- C3 vs B
    t, r = PRIMARY
    x = _contrast_frame(d, t, r, None)
    p1 = lpm_did(x)
    g = per_game_d(x)
    p2 = {"est": game_did(g, t, r), "p": permutation_p(g, t, r, args.perms, rng),
          "ci97.5": bootstrap_ci(g, t, r, args.boots, rng, 1 - ALPHA_PRIMARY), "n_games": len(g)}
    agree = (np.sign(p1["est"]) == np.sign(p2["est"]))
    report["primary"] = {
        "P1 per-decision LPM DiD": p1, "P2 per-game DiD": p2,
        "supported": bool(agree and p1["p"] < ALPHA_PRIMARY and p2["p"] < ALPHA_PRIMARY),
        "sensitivity": {
            "valid decisions only": lpm_did(x[x.valid]),
            "logit AME DiD": logit_ame_did(x),
            "first subject decision per round": lpm_did(
                x.sort_values("play_index").groupby(["game", "round"]).head(1)),
        },
        "per_model (descriptive)": {m: lpm_did(xm) for m, xm in x.groupby("model")},
    }

    # SECONDARY S1-S6, Holm
    sec = {name: lpm_did(_contrast_frame(d, a, b, restr)) for name, (a, b, restr) in SECONDARY.items()}
    adj = holm({k: v["p"] for k, v in sec.items()})
    for k in sec:
        sec[k]["p_holm"] = adj[k]
    report["secondary"] = sec

    # Study 2 positive control
    report["study2"] = study2(d, games)

    tbl = pass_table(d)
    report["descriptive_pass_rates"] = tbl.to_dict(orient="records")

    def fmt(v):
        if isinstance(v, float):
            return round(v, 4)
        if isinstance(v, (np.floating, np.integer, np.bool_)):
            return fmt(v.item())
        if isinstance(v, dict):
            return {k: fmt(w) for k, w in v.items()}
        if isinstance(v, (list, tuple)):
            return [fmt(w) for w in v]
        return v

    text = json.dumps(fmt(report), indent=2, default=str)
    print(text)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "analysis.json").write_text(text)
        tbl.to_csv(out / "pass_rates.csv", index=False)
        d.to_csv(out / "decisions.csv", index=False)
        games.to_csv(out / "games.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

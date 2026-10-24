"""Collect every number used in the report from the saved data and results (no API calls).
Usage: python report/collect_numbers.py  -> writes report/numbers.json and prints a summary."""
import collections, glob, json, statistics as st, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "scripts")
import analyse as A
import study1_extras as E

out = {}

# ---------------- Study 2: single games (runs/main/study2)
d2, g2 = A.load(Path("runs/main/study2"), include_pilot=False)
s2 = A.study2(d2, g2)
out["study2_tests"] = {k: {kk: float(vv) for kk, vv in v.items()} for k, v in s2.items()}
g2 = g2.set_index("game")
d2["formed"] = d2.game.map(g2.scc_active).eq(True)
pairs = d2[((d2.judge == "T") & (d2.actor == "X")) | ((d2.judge == "X") & (d2.actor == "T"))]
others = d2[((d2.judge == "T") & (d2.actor == "S")) | ((d2.judge == "X") & (d2.actor == "H"))]
out["study2_partner_pass"] = {
    "A0": [float(pairs[pairs.arm == "A0"].pass_.mean()), int((pairs.arm == "A0").sum())],
    "A1_all": [float(pairs[pairs.arm == "A1"].pass_.mean()), int((pairs.arm == "A1").sum())],
    "A1_formed": [float(pairs[(pairs.arm == "A1") & pairs.formed].pass_.mean()), int(((pairs.arm == "A1") & pairs.formed).sum())],
}
out["study2_outsider_pass"] = {
    "A0": float(others[others.arm == "A0"].pass_.mean()),
    "A1_formed": float(others[(others.arm == "A1") & others.formed].pass_.mean()),
}
a1 = g2[g2.arm == "A1"]
out["study2_formed"] = f"{int(a1.scc_active.eq(True).sum())}/{len(a1)}"
first_out = collections.Counter(); winner = collections.Counter(); partner_dec = []
t_accept = collections.Counter()
for f in glob.glob("runs/main/study2/*/*/seed*.jsonl"):
    ev = [json.loads(l) for l in open(f)]
    e = [x for x in ev if x["type"] == "game_end"][0]
    first_out[e["elimination_order"][0] in ("T", "X")] += 1
    winner[e["winner_role"]] += 1
    partner_dec.append(sum(1 for x in ev if x["type"] == "decision" and {x["judge"], x["actor"]} == {"T", "X"}))
    for x in ev:
        if x["type"] == "llm_call" and x["purpose"] == "scc_offer":
            r = x["response"].strip().upper()
            t_accept["accept" if "ACCEPT" in r[:20] else "refuse" if "REFUSE" in r[:20] else "other"] += 1
out["study2_games"] = len(partner_dec)
out["study2_first_out_TX"] = first_out[True]
out["study2_winner"] = dict(winner)
out["study2_partner_decisions_median"] = st.median(partner_dec)
out["study2_T_offer_replies"] = dict(t_accept)
out["study2_by_model"] = {}
for m, sub in pairs.groupby("model"):
    out["study2_by_model"][m] = {a: [float(sub[sub.arm == a].pass_.mean()), int((sub.arm == a).sum())] for a in ("A0", "A1")}

# ---------------- Series follow-up (runs/series)
msgs = pd.read_csv("results/series_messages.csv")
msgs = msgs[msgs.parsed == True]
flags = ["hand_sharing", "target_selection", "non_challenge_pact", "hostile_to_partner"]
for c in flags:
    msgs[c] = msgs[c].astype(str).str.lower().eq("true")
out["series_messages"] = {"n": int(len(msgs)), **{c: float(msgs[c].mean()) for c in flags},
                          "by_sender": {s: {c: float(g[c].mean()) for c in flags} | {"n": int(len(g))} for s, g in msgs.groupby("from")}}
out["series_analysis_text"] = Path("results/series_analysis.txt").read_text()

# ---------------- Study 1 restart (runs/study1_v2)
rep = json.loads(Path("results/study1_v2/analysis.json").read_text())
out["s1_primary"] = rep["primary"]
out["s1_secondary"] = rep["secondary"]
out["s1_holm_S1_S5"] = E.holm({k: rep["secondary"][k]["p"] for k in E.TESTED})
d1, g1 = A.load(Path("runs/study1_v2"), include_pilot=False)
hs = d1[d1.actor.isin(["H", "S"])]
raw = hs.groupby(["arm", "actor"]).pass_.agg(["mean", "count"])
out["s1_pass_pooled"] = {f"{a}|{b}": [float(r["mean"]), int(r["count"])] for (a, b), r in raw.iterrows()}
out["s1_gap_pooled"] = {a: float(raw.loc[(a, "H"), "mean"] - raw.loc[(a, "S"), "mean"]) for a in ("C0", "B", "C2", "C3", "C3NE")}
per_model = hs.groupby(["model", "arm", "actor"]).pass_.mean()
out["s1_pass_by_model"] = {f"{m}|{a}|{x}": float(v) for (m, a, x), v in per_model.items()}
# cluster bootstrap 95% CI of each arm's raw gap (games resampled within arm)
rng = np.random.default_rng(20261024)
ci = {}
for a, sub in hs.groupby("arm"):
    games = sub.game.unique(); by = {g: s for g, s in sub.groupby("game")}
    vals = []
    for _ in range(2000):
        pick = pd.concat([by[g] for g in rng.choice(games, len(games), replace=True)])
        h, s = pick[pick.actor == "H"].pass_.mean(), pick[pick.actor == "S"].pass_.mean()
        vals.append(h - s)
    ci[a] = [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]
out["s1_gap_ci95"] = ci
# extra comparisons (not pre-registered) and loop robustness
meta = E.game_meta(Path("runs/study1_v2"))
loops = set(meta.loc[meta.loop, "game"])
out["s1_loops_total"] = len(loops)
out["s1_loops_by_arm"] = meta.groupby("arm").loop.sum().astype(int).to_dict()
rob = {}
for label, dd in (("all", d1), ("no_loops", d1[~d1.game.isin(loops)])):
    for a, b in (("C3", "B"), ("C2", "B"), ("C3", "C2"), ("C2", "C0")):
        x = A._contrast_frame(dd, a, b, None)
        r = A.lpm_did(x); g = A.per_game_d(x)
        rob[f"{label}|{a}-{b}"] = {"lpm": float(r["est"]), "lpm_p": float(r["p"]), "game": float(A.game_did(g, a, b)),
                                   "perm_p": float(A.permutation_p(g, a, b, 10000, np.random.default_rng(7)))}
out["s1_robustness"] = rob
out["s1_c2_vs_b_by_model"] = {m: {k: float(v) for k, v in A.lpm_did(xm).items()} for m, xm in A._contrast_frame(d1, "C2", "B", None).groupby("model")}
# interview
iv = {}
for a, sub in meta.groupby("arm"):
    n = 2 * len(sub)
    iv[a] = {"least_is_H": float((sub.T_least_is_H.sum() + sub.X_least_is_H.sum()) / n),
             "agreed": float((sub.T_agreed.sum() + sub.X_agreed.sum()) / n),
             "unusual_is_H": float((sub.T_unusual_is_H.sum() + sub.X_unusual_is_H.sum()) / n), "subjects": n}
out["s1_interview"] = iv
# verbal replies
rp = pd.read_csv("results/study1_v2/replies.csv")
h = rp[(rp.sender == "H") & (rp.label != "UNPARSED")].copy()
h["proposes"] = h.proposes.astype(str).str.lower().eq("true")
h["suspicion"] = h.suspicion.astype(str).str.lower().eq("true")
out["s1_replies"] = {a: {**{k: float(v) for k, v in sub.label.value_counts(normalize=True).items()},
                         "n": int(len(sub)), "proposes": float(sub.proposes.mean()), "suspicion_flag": float(sub.suspicion.mean())}
                     for a, sub in h.groupby("arm")}
out["s1_replies_accept_by_model"] = {f"{m}|{a}": float(s.label.eq("ACCEPT").mean()) for (m, a), s in h.groupby(["model", "arm"])}
out["s1_replies_to_S_labels"] = rp[rp.sender == "S"].label.value_counts().to_dict()
acc = h[h.label == "ACCEPT"].copy(); mm = meta.set_index("game")
acc["said_agreed"] = [mm.loc[g, f"{s}_agreed"] for g, s in zip(acc.game, acc.subject)]
out["s1_concealment"] = {a: [float((~s.said_agreed).mean()), int(len(s))] for a, s in acc.groupby("arm")}
# decisions per game and winners
dec = hs.groupby(["model", "game"]).size().groupby("model").median().to_dict()
out["s1_HS_decisions_per_game_median"] = {k: float(v) for k, v in dec.items()}
w = collections.Counter(); fo = collections.Counter()
for f in glob.glob("runs/study1_v2/study1/*/*/seed*.jsonl"):
    for line in open(f):
        if '"game_end"' in line:
            e = json.loads(line); w[e["winner_role"]] += 1
            fo[e["elimination_order"][0] if e["elimination_order"] else None] += 1
out["s1_winner_roles"] = dict(w); out["s1_first_eliminated"] = {str(k): v for k, v in fo.items()}

# ---------------- costs from logs
def cost(pattern):
    return sum((json.loads(l).get("cost_usd") or 0) for f in glob.glob(pattern, recursive=True) for l in open(f) if '"llm_call"' in l)
out["costs"] = {
    "study2_single": cost("runs/main/study2/**/*.jsonl"),
    "study1_first_attempt": cost("runs/main/study1/**/*.jsonl"),
    "pilots_old": cost("runs/pilot/**/*.jsonl") + cost("runs/pilot2/**/*.jsonl") + cost("runs/smoke*/**/*.jsonl"),
    "series_smoke": cost("runs/series_smoke/**/*.jsonl"),
    "series": cost("runs/series/**/*.jsonl"),
    "s1_restart_pilots": cost("runs/pilot_s1v2/**/*.jsonl") + cost("runs/pilot_s1v2b/**/*.jsonl"),
    "study1_restart": cost("runs/study1_v2/**/*.jsonl"),
}
Path("report/numbers.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps({k: v for k, v in out.items() if k != "series_analysis_text"}, indent=1, default=str)[:12000])

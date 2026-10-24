"""Figures for the report, from report/numbers.json and the saved game logs (no API calls).
Usage: python report/make_figures.py  -> report/fig_*.png"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, "scripts")
import analyse as A  # noqa: E402
import analyse_series as S  # noqa: E402

N = json.loads(Path("report/numbers.json").read_text())
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"  # validated categorical slots 1-4 (light)
GRAY, INK, INK2, GRID = "#a3a29c", "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": "white"})
VERS = [("C0", "No offer (C0)"), ("B", "Friendly request (B)"), ("C2", "Hint (C2)"), ("C3", "Direct deal (C3)"),
        ("C3NE", "Deal, no reminders (C3NE)")]

# ---- Figure 1: favouritism gap per version (pass rate on H minus on S), pooled, 95% CI
fig, ax = plt.subplots(figsize=(6.4, 2.6))
for i, (k, lab) in enumerate(VERS[::-1]):
    g = 100 * N["s1_gap_pooled"][k]
    lo, hi = (100 * v for v in N["s1_gap_ci95"][k])
    ax.plot([lo, hi], [i, i], color=BLUE, lw=2, solid_capstyle="round")
    ax.plot(g, i, "o", ms=8, color=BLUE, mec="white", mew=2)
    ax.text(hi + 1.2, i, f"{g:+.1f}", va="center", fontsize=8.5, color=INK)
ax.axvline(0, color=INK2, lw=1)
ax.set_yticks(range(len(VERS)), [lab for _, lab in VERS[::-1]])
ax.set_xlabel("Pass rate on H minus pass rate on S (percentage points)")
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
ax.set_xlim(-18, 20)
fig.tight_layout(); fig.savefig("report/fig_study1_gap.png", dpi=200); plt.close(fig)

# ---- Figure 2: first reply to H's first note, share of labels per version
labels = [("ACCEPT", "Accept", BLUE), ("REFUSE", "Refuse", ORANGE), ("SUSPICIOUS", "Suspicious", AQUA),
          ("OTHER", "Other / small talk", GRAY)]
fig, ax = plt.subplots(figsize=(6.4, 2.6))
for i, (k, lab) in enumerate(VERS[::-1]):
    left = 0.0
    for key, name, col in labels:
        w = 100 * N["s1_replies"][k].get(key, 0.0)
        if w <= 0:
            continue
        ax.barh(i, w, left=left, color=col, edgecolor="white", linewidth=2, height=0.62)
        if w >= 7:
            ax.text(left + w / 2, i, f"{w:.0f}%", ha="center", va="center", fontsize=8,
                    color="white" if col in (BLUE, ORANGE) else INK)
        left += w
ax.set_yticks(range(len(VERS)), [lab for _, lab in VERS[::-1]])
ax.set_xlim(0, 100); ax.set_xlabel("Share of first replies to H (%)")
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in labels]
ax.legend(handles, [n for _, n, _ in labels], ncol=4, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0),
          fontsize=8, handlelength=1.2)
fig.tight_layout(); fig.savefig("report/fig_study1_replies.png", dpi=200); plt.close(fig)

# ---- Figure 3: series follow-up, partners' pass rate on each other by game number
info = S.series_info(Path("runs/series"))
info = info[info.series_seed < A.PILOT_SEED_MIN]
d, _ = A.load(Path("runs/series"), include_pilot=True)
d = d.merge(info[["game", "series_game"]], on="game", how="inner")
part = d[((d.judge == "T") & (d.actor == "X")) | ((d.judge == "X") & (d.actor == "T"))]
by = part.groupby(["series_game", "arm"]).pass_.mean().unstack()
fig, ax = plt.subplots(figsize=(6.4, 2.5))
ax.plot(by.index, 100 * by["A1F"], "-o", color=BLUE, lw=2, ms=4, label="With offer at game 15 (10 tables)")
ax.plot(by.index, 100 * by["A0F"], "-o", color=ORANGE, lw=2, ms=4, label="No offer (10 tables)")
ax.axvline(14.5, color=INK2, lw=1, ls="--")
ax.text(14.6, 97, "offer", fontsize=8, color=INK2, va="top")
ax.set_xlabel("Game number in the 20-game series"); ax.set_ylabel("Partner lets partner pass (%)")
ax.set_xticks(range(1, 21)); ax.set_ylim(30, 100)
ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
fig.tight_layout(); fig.savefig("report/fig_series_partner.png", dpi=200); plt.close(fig)
print("figures written")

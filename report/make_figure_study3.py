"""Figure for Study 3: the effect of each approach against the control, from the frozen analysis's analysis.json.
Usage: python report/make_figure_study3.py results/study3/analysis.json report/fig_study3.png"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BLUE, ORANGE, INK, INK2, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": "white"})
NAMES = {"PF": "Fair-play appeal (PF)", "PE": "Warning (PE)", "PT": "Temptation (PT)", "PC": "Counter-offer (PC)"}

res = json.load(open(sys.argv[1]))["primary"]
fig, ax = plt.subplots(figsize=(6.2, 2.5))
rows = list(NAMES)[::-1]
for i, a in enumerate(rows):
    for off, key, col, lab in ((0.14, None, BLUE, "Favouritism toward the partner (partner minus decoy)"),
                               (-0.14, "partner_only", ORANGE, "Partners' pass rate on each other")):
        r = res[a] if key is None else res[a][key]
        est, (lo, hi) = 100 * r["est"], (100 * r["ci95"][0], 100 * r["ci95"][1])
        ax.plot([lo, hi], [i + off, i + off], color=col, lw=2, solid_capstyle="round")
        ax.plot(est, i + off, "o", ms=7, color=col, mec="white", mew=1.5, label=lab if i == 0 else None)
        ax.text(hi + 1.5, i + off, f"{est:+.1f}".replace("-", "\u2212"), va="center", fontsize=8, color=INK)
ax.axvline(0, color=INK2, lw=1)
ax.set_yticks(range(len(rows)), [NAMES[a] for a in rows])
ax.set_xlabel("Change against the control (percentage points; 95% interval)")
ax.grid(axis="x", color=GRID, lw=0.8)
ax.set_axisbelow(True)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2, frameon=False, fontsize=8)
fig.tight_layout()
fig.savefig(sys.argv[2], dpi=200, bbox_inches="tight")
print("wrote", sys.argv[2])

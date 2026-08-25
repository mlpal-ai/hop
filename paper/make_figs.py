#!/usr/bin/env python3
"""HOP paper figures as vector PDFs, styled to match the yodex paper (Times, muted palette)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 9,
    "axes.edgecolor": "#33414F",
    "axes.linewidth": 0.7,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
})

INK = "#16202B"
ACCENT = "#1B3A5B"   # profile-ized build
GRAY = "#9AA0A6"     # pre-split 0.8.0
GOOD = "#2E7D4F"
BAD = "#B23A2E"
GOLD = "#C08A2E"

os.makedirs("fig", exist_ok=True)

# ---------------------------------------------------- Figure: H1 fidelity (paired benchmark)
def fig_parity():
    tasks = ["ledger\n(easy)", "slug\n(easy)", "scheduler\n(hard)", "ratelimit\n(hard)"]
    pre = [3298, 2886, 28021, 13051]     # 0.8.0 output tokens, mean of 2
    post = [2382, 2423, 19627, 13544]    # profile-ized build
    pre_w = [48.1, 50.4, 396.6, 162.7]
    post_w = [39.0, 38.7, 282.6, 172.3]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(6.4, 2.5))
    x = range(len(tasks)); w = 0.36
    lab = lambda v: f"{v/1000:.1f}k" if v >= 10000 else f"{v:,}"

    axL.bar([i - w/2 for i in x], pre, width=w, color=GRAY, label="pre-split 0.8.0")
    axL.bar([i + w/2 for i in x], post, width=w, color=ACCENT, label="engine + coding HOP")
    axL.set_yscale("log")
    for i, (a, b) in enumerate(zip(pre, post)):
        axL.text(i - w/2, a * 1.12, lab(a), ha="center", fontsize=6.4, color="#6B7178")
        axL.text(i + w/2, b * 1.12, lab(b), ha="center", fontsize=6.4, color=ACCENT)
    axL.set_xticks(list(x)); axL.set_xticklabels(tasks, fontsize=7.6)
    axL.set_ylabel("output tokens / task (log)", fontsize=8.2)
    axL.set_title("Tokens — every cell 2/2 correct on both builds", fontsize=8.2)
    axL.legend(fontsize=7.0, frameon=False, loc="upper left")

    axR.bar([i - w/2 for i in x], pre_w, width=w, color=GRAY)
    axR.bar([i + w/2 for i in x], post_w, width=w, color=ACCENT)
    for i, (a, b) in enumerate(zip(pre_w, post_w)):
        axR.text(i - w/2, a + 8, f"{a:.0f}", ha="center", fontsize=6.4, color="#6B7178")
        axR.text(i + w/2, b + 8, f"{b:.0f}", ha="center", fontsize=6.4, color=ACCENT)
    axR.set_xticks(list(x)); axR.set_xticklabels(tasks, fontsize=7.6)
    axR.set_ylabel("wall seconds / task", fontsize=8.2)
    axR.set_title("Wall clock", fontsize=8.2)
    axR.set_ylim(0, 440)

    for ax in (axL, axR):
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    fig.tight_layout(pad=0.6)
    fig.savefig("fig/fig_parity.pdf", bbox_inches="tight")
    plt.close(fig)

fig_parity()
print("figures written")

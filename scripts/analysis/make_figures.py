#!/usr/bin/env python3
"""Generate publication-grade Nord figures for MFC H200 AP Optimization."""
import argparse
import csv
import pathlib
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


ROOT = pathlib.Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "results" / "summary"
FIGS = ROOT / "figures"

NORD = {
    "bg": "#ECEFF4",
    "card": "#FFFFFF",
    "ink": "#2E3440",
    "sub": "#4C566A",
    "grid": "#D8DEE9",
    "frost0": "#8FBCBB",
    "frost1": "#88C0D0",
    "frost2": "#81A1C1",
    "frost3": "#5E81AC",
    "red": "#BF616A",
    "orange": "#D08770",
    "yellow": "#EBCB8B",
    "green": "#A3BE8C",
    "purple": "#B48EAD",
}

plt.rcParams.update(
    {
        "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.facecolor": NORD["bg"],
        "axes.facecolor": NORD["card"],
        "axes.edgecolor": NORD["grid"],
        "axes.labelcolor": NORD["ink"],
        "xtick.color": NORD["sub"],
        "ytick.color": NORD["sub"],
        "text.color": NORD["ink"],
        "savefig.dpi": 220,
    }
)


def read_csv(path: pathlib.Path):
    with path.open() as f:
        return list(csv.DictReader(f))


def make_fig1():
    rows = [r for r in read_csv(SUMMARY / "kernel_breakdown.csv") if r["profile_tag"] == "B0_1gpu"]
    grp_ms = defaultdict(float)
    total_ms_all = 0.0
    for r in rows:
        ms = float(r["ms_per_rhs"])
        grp_ms[r["kernel_group"]] += ms
        total_ms_all += ms

    ordered = sorted(grp_ms.items(), key=lambda x: x[1])
    labels = [k for k, _ in ordered]
    vals = [v for _, v in ordered]
    pcts = [v / total_ms_all * 100.0 for v in vals]

    colors = []
    for k in labels:
        if "WENO5" in k:
            colors.append(NORD["frost3"])
        elif "HLLC" in k:
            colors.append(NORD["red"])
        elif "Dead" in k:
            colors.append(NORD["orange"])
        elif "Advection" in k or "Cons" in k:
            colors.append(NORD["frost2"])
        else:
            colors.append(NORD["frost1"])

    fig, ax = plt.subplots(figsize=(10.5, 5.4), constrained_layout=True)
    bars = ax.barh(labels, vals, color=colors, height=0.62, edgecolor=NORD["ink"], linewidth=0.5)
    ax.grid(axis="x", color=NORD["grid"], linestyle="--", alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlabel("GPU Kernel Time per RHS Stage (ms/rhs, 256^3 Single H200)")
    ax.set_title("MFC Baseline (B0) 3D Shock-Droplet GPU Hotspot Profile (nsys, 10 steps / 30 RHS)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlim(0, max(vals) * 1.32)

    for b, v, p in zip(bars, vals, pcts):
        ax.text(
            v + 0.45,
            b.get_y() + b.get_height() / 2,
            f"{v:.2f} ms/rhs  ({p:.1f}%)",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=NORD["ink"],
        )

    note = (
        "Key Bottlenecks (Job 795079 + cuobjdump):\n"
        "- WENO5 (180-182 REG): 46.7% GPU time\n"
        "- HLLC (145-176 REG, 368-480 B STACK): 37.8% GPU time\n"
        "- WENO5 + HLLC combined = 84.5% of GPU compute"
    )
    ax.text(
        0.53,
        0.09,
        note,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        bbox=dict(boxstyle="round,pad=0.55", facecolor=NORD["bg"], edgecolor=NORD["frost3"], linewidth=1.1),
    )

    out = FIGS / "fig1_baseline_hotspots.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


def make_fig2():
    rows = read_csv(SUMMARY / "ablation_1gpu.csv")
    if not rows:
        return
    name_map = {
        "B0": "B0\nBaseline",
        "L1_stock": "L1_stock\nUpstream CaseOpt",
        "L1": "+L1\n18 Solver Switches",
        "L12": "+L2\nRHS DeadWork/1/dx",
        "L123": "+L3\nWENO5+HLLC+EOS",
        "L1234": "+L4 (1-GPU)\nMPI Halo Ctrl",
    }
    labels = [name_map.get(r["arm"], r["arm"]) for r in rows]
    meds = [float(r["retained_med_ms_rhs"]) for r in rows]
    mins = [float(r["retained_min_ms_rhs"]) for r in rows]
    maxs = [float(r["retained_max_ms_rhs"]) for r in rows]
    spds = [float(r["speedup_vs_B0"]) for r in rows]

    yerr_lo = [m - lo for m, lo in zip(meds, mins)]
    yerr_hi = [hi - m for m, hi in zip(meds, maxs)]
    bar_colors = [NORD["sub"], NORD["frost2"], NORD["frost1"], NORD["frost0"], NORD["green"], NORD["frost3"]][: len(rows)]

    fig, ax = plt.subplots(figsize=(10.5, 5.5), constrained_layout=True)
    x = list(range(len(labels)))
    bars = ax.bar(x, meds, width=0.56, color=bar_colors, edgecolor=NORD["ink"], linewidth=0.6)
    ax.errorbar(x, meds, yerr=[yerr_lo, yerr_hi], fmt="none", ecolor=NORD["ink"], elinewidth=1.4, capsize=5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5)
    ax.set_ylabel("Median Time per RHS (ms/rhs, lower is faster)")
    ax.set_title("Single-H200 Pinned Ablation Ladder (256^3, 30 steps, 4 retained reps; Error bars = [min, max])", fontsize=12.5, fontweight="bold", pad=12)
    ax.set_ylim(0, max(maxs) * 1.24)
    ax.grid(axis="y", color=NORD["grid"], linestyle="--", alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for b, m, sp in zip(bars, meds, spds):
        ax.text(
            b.get_x() + b.get_width() / 2,
            m + max(maxs) * 0.035,
            f"{m:.2f} ms\n({sp:.2f}x)",
            ha="center",
            va="bottom",
            fontsize=9.5,
            fontweight="bold",
        )

    out = FIGS / "fig2_ablation_waterfall.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


def make_fig3():
    rows = read_csv(SUMMARY / "kernel_breakdown.csv")
    tags = sorted(set(r["profile_tag"] for r in rows))
    final_tags = [t for t in tags if t != "B0_1gpu" and t.endswith("_1gpu")]
    if not final_tags:
        return
    ftag = final_tags[0]

    groups = [
        "WENO5 (m_weno)",
        "HLLC Riemann (m_riemann)",
        "Advection Src (m_rhs)",
        "Cons->Prim (m_vars_conv)",
        "TVD-RK3 (m_time_steppers)",
        "Dead idwbuff Copy (m_rhs_646)",
    ]
    b0_map = defaultdict(float)
    fin_map = defaultdict(float)
    for r in rows:
        if r["profile_tag"] == "B0_1gpu":
            b0_map[r["kernel_group"]] += float(r["ms_per_rhs"])
        elif r["profile_tag"] == ftag:
            fin_map[r["kernel_group"]] += float(r["ms_per_rhs"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.0, 5.2), gridspec_kw={"width_ratios": [1.45, 1.0]}, constrained_layout=True)

    y = list(range(len(groups)))
    h = 0.36
    b0_vals = [b0_map[g] for g in groups]
    fin_vals = [fin_map[g] for g in groups]
    ax1.barh([i + h / 2 for i in y], b0_vals, height=h, color=NORD["sub"], label="B0 (Baseline)")
    ax1.barh([i - h / 2 for i in y], fin_vals, height=h, color=NORD["green"], label=ftag)
    ax1.set_yticks(y)
    ax1.set_yticklabels(groups, fontsize=9.5)
    ax1.invert_yaxis()
    ax1.set_xlabel("GPU Kernel Time per RHS (ms/rhs)")
    ax1.set_title("Per-Kernel GPU Latency: B0 vs Final (1xH200)", fontsize=11.5, fontweight="bold")
    ax1.grid(axis="x", color=NORD["grid"], linestyle="--", alpha=0.8)
    ax1.set_axisbelow(True)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="lower right", frameon=True)
    ax1.set_xlim(0, max(b0_vals) * 1.25)
    for i, (bv, fv) in enumerate(zip(b0_vals, fin_vals)):
        ax1.text(bv + 0.3, i + h / 2, f"{bv:.2f}", va="center", fontsize=8.5, color=NORD["sub"])
        pct = ((bv - fv) / bv * 100.0) if bv > 0 else 0.0
        ax1.text(fv + 0.3, i - h / 2, f"{fv:.2f} (-{pct:.0f}%)", va="center", fontsize=8.5, fontweight="bold", color=NORD["frost3"])

    # Right panel: Stack bytes / Register summary of ACTIVE executed kernels from nsys + cuobjdump
    reg_rows = read_csv(SUMMARY / "register_stack.csv")
    final_arm = ftag.replace("nsys_", "").replace("_1gpu", "")

    def executed_prefix(profile_tag, grp_kw, fallback_kw):
        sub = [r["kernel_name"] for r in rows if r["profile_tag"] == profile_tag and grp_kw in r["kernel_group"]]
        if not sub:
            return fallback_kw
        # Strip trailing _1 / __1 / _2 / __2 directional instance suffix
        import re
        return re.sub(r"_+[12]$", "", sub[0])

    def peak_res(arm, prof_tag, grp_kw, fallback_kw):
        pref = executed_prefix(prof_tag, grp_kw, fallback_kw)
        sub = [r for r in reg_rows if r["arm"] == arm and pref in r["kernel"]]
        if not sub:
            sub = [r for r in reg_rows if r["arm"] == arm and fallback_kw in r["kernel"]]
        if not sub:
            return (0, 0)
        return (max(int(r["registers"]) for r in sub), max(int(r["stack_bytes"]) for r in sub))

    k_defs = [
        ("WENO5", "WENO5", "m_weno_s_weno_"),
        ("HLLC", "HLLC", "s_hllc_riemann_solver_"),
        ("VarConv", "Cons->Prim", "convert_conservative_to_primitive"),
    ]
    b0_res = [peak_res("B0", "B0_1gpu", gkw, fkw) for _, gkw, fkw in k_defs]
    fin_res = [peak_res(final_arm, ftag, gkw, fkw) for _, gkw, fkw in k_defs]
    b0_stacks = [r[1] for r in b0_res]
    fin_stacks = [r[1] for r in fin_res]
    b0_regs = [r[0] for r in b0_res]
    fin_regs = [r[0] for r in fin_res]

    xk = list(range(len(k_defs)))
    ax2.bar([i - 0.18 for i in xk], b0_stacks, width=0.34, color=NORD["red"], label="B0 Stack (B/thread)")
    ax2.bar([i + 0.18 for i in xk], fin_stacks, width=0.34, color=NORD["frost1"], label=f"{final_arm} Stack (B/thread)")
    ax2.set_xticks(xk)
    ax2.set_xticklabels([f"{lbl}\nREG {r0}->{r1}" for (lbl, _, _), r0, r1 in zip(k_defs, b0_regs, fin_regs)], fontsize=9.5)
    ax2.set_ylabel("Local Memory Stack Spill (Bytes / Thread)")
    ax2.set_title("cuobjdump Register & Local Spill Reduction", fontsize=11.5, fontweight="bold")
    ax2.grid(axis="y", color=NORD["grid"], linestyle="--", alpha=0.8)
    ax2.set_axisbelow(True)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.legend(loc="upper right")
    ax2.set_ylim(0, max(max(b0_stacks), 100) * 1.25)
    for i, (s0, s1) in enumerate(zip(b0_stacks, fin_stacks)):
        ax2.text(i - 0.18, s0 + 12, f"{s0} B", ha="center", fontsize=9, fontweight="bold", color=NORD["red"])
        ax2.text(i + 0.18, s1 + 12, f"{s1} B", ha="center", fontsize=9, fontweight="bold", color=NORD["frost3"])

    out = FIGS / "fig3_kernel_before_after.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


def make_fig4():
    rows = read_csv(SUMMARY / "scaling_1to8gpu.csv")
    if not rows:
        return
    by_cfg = defaultdict(dict)
    for r in rows:
        by_cfg[r["config"]][int(r["np"])] = (float(r["rhs_per_s_med"]), float(r["parallel_efficiency_pct"]))
    for cfg, d in list(by_cfg.items()):
        if "rdmaT" in cfg and 1 not in d:
            sib = cfg.replace("rdmaT", "rdmaF")
            if sib in by_cfg and 1 in by_cfg[sib]:
                d[1] = by_cfg[sib][1]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.8, 5.0), constrained_layout=True)
    style_map = {
        "scale_B0_rdmaF": ("Baseline B0 (rdma=F)", NORD["sub"], "o", "--"),
    }
    for cfg in sorted(by_cfg.keys()):
        if cfg not in style_map:
            if "rdmaT" in cfg:
                style_map[cfg] = ("Optimized Final (SoA + rdma=T)", NORD["green"], "D", "-")
            else:
                style_map[cfg] = ("Optimized Final (SoA + rdma=F)", NORD["frost3"], "s", "-")

    nps = [1, 2, 4, 8]
    for cfg, d in sorted(by_cfg.items()):
        lbl, col, mkr, ls = style_map[cfg]
        xs = sorted(d.keys())
        ys = [d[x][0] for x in xs]
        effs = [d[x][1] for x in xs]
        ax1.plot(xs, ys, marker=mkr, linestyle=ls, linewidth=2.2, markersize=7, color=col, label=lbl)
        ax2.plot(xs, effs, marker=mkr, linestyle=ls, linewidth=2.2, markersize=7, color=col, label=lbl)

    ax1.set_xticks(nps)
    ax1.set_xlabel("Number of H200 GPUs (Single Node NVSwitch)")
    ax1.set_ylabel("Throughput (RHS stages / sec, 256^3 Strong Scaling)")
    ax1.set_title("1-8xH200 Strong Scaling Throughput (256^3)", fontsize=11.5, fontweight="bold")
    ax1.grid(True, color=NORD["grid"], linestyle="--", alpha=0.8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.legend(loc="upper left", fontsize=9)

    ax2.axhline(100.0, color=NORD["red"], linestyle=":", linewidth=1.2, label="Ideal (100%)")
    ax2.set_xticks(nps)
    ax2.set_xlabel("Number of H200 GPUs (Single Node NVSwitch)")
    ax2.set_ylabel("Strong-Scaling Parallel Efficiency (%) vs Own 1-GPU")
    ax2.set_title("Parallel Efficiency Across NVLink / RDMA Paths", fontsize=11.5, fontweight="bold")
    ax2.set_ylim(0, 118)
    ax2.grid(True, color=NORD["grid"], linestyle="--", alpha=0.8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    ax2.legend(loc="lower left", fontsize=9)

    out = FIGS / "fig4_strong_scaling_8gpu.png"
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


def make_fig5():
    fig, ax = plt.subplots(figsize=(12.2, 6.2))
    fig.patch.set_facecolor(NORD["bg"])
    ax.set_facecolor(NORD["bg"])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 62)
    ax.axis("off")

    ax.text(
        50,
        58.5,
        "Closed-Loop Multi-Agent Research Workflow for MFC H200 Optimization",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=NORD["ink"],
    )
    ax.text(
        50,
        55.0,
        "Separation of Concerns: Planner/Builder  |  Read-Only Critics  |  Strict Slurm Hardware Gates  |  Zero-Hallucination Provenance",
        ha="center",
        va="center",
        fontsize=10,
        color=NORD["sub"],
    )

    def box(x, y, w, h, title, body, fc, ec, title_col=NORD["ink"]):
        patch = mpatches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.6,rounding_size=1.4",
            facecolor=fc,
            edgecolor=ec,
            linewidth=2.0,
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h - 2.3, title, ha="center", va="top", fontsize=10.5, fontweight="bold", color=title_col)
        ax.text(x + w / 2, y + h / 2 - 1.3, body, ha="center", va="center", fontsize=8.8, color=NORD["ink"], linespacing=1.35)

    def arrow(x1, y1, x2, y2, label="", rad=0.0, col=NORD["frost3"], lx_off=0.0, ly_off=1.2):
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle="-|>,head_width=0.5,head_length=0.8", lw=2.0, color=col, connectionstyle=f"arc3,rad={rad}"),
        )
        if label:
            mx, my = (x1 + x2) / 2 + lx_off, (y1 + y2) / 2 + ly_off
            ax.text(mx, my, label, ha="center", va="center", fontsize=8.3, fontweight="bold", color=col,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=NORD["bg"], edgecolor="none", alpha=0.85))

    # Row 1: Discovery & Audit
    box(3, 36, 26, 14, "1. Code Scout (Read-Only Subagent)", "Indexed m_weno, HLLC, VarConv,\ncase.py & m_mpi_common\n-> Identified 84.5% hotspot + spills", "#FFFFFF", NORD["frost1"])
    box(37, 36, 26, 14, "2. Planner + Plan Critic Split", "PREREG hypotheses L1..L4\nIndependent critic caught macro\nleaks, low_Mach & ghost hazards", "#FFFFFF", NORD["frost3"])
    box(71, 36, 26, 14, "3. Patch Authoring (L1..L4)", "Local MFC-src branch ap-opt\n4 clean git-apply patches + static\nline/bijection verification", "#FFFFFF", NORD["frost2"])

    # Row 2: Execution & Deliverables
    box(71, 12, 26, 15, "4. Nano4 H200 Hardware Gate", "Pinned single-alloc Slurm runs\nGate 3A L2 <= 1e-11 vs Golden B0\ncuobjdump + nsys + ncu + 8-GPU", "#FFFFFF", NORD["orange"])
    box(37, 12, 26, 15, "5. Provenance Verifier Subagent", "Fresh read-only audit matching\nevery number to SOURCES.md\nand raw Nano4 CSV/JSON/logs", "#FFFFFF", NORD["red"])
    box(3, 12, 26, 15, "6. Synthesis & Multimedia Delivery", "Standalone repo (zero remotes)\nREPORT-zh.pdf + 13 Nord Slides\nzh-TW Neural TTS + 1080p MP4", "#FFFFFF", NORD["green"])

    arrow(29.8, 43, 36.2, 43, "Hotspot Map", ly_off=1.7)
    arrow(63.8, 43, 70.2, 43, "Reviewed Spec", ly_off=1.7)
    arrow(84, 35.2, 84, 27.8, "SSH Master / sbatch", lx_off=7.6, ly_off=0.0, col=NORD["orange"])
    arrow(70.2, 19.5, 63.8, 19.5, "PASS Data", ly_off=1.8, col=NORD["red"])
    arrow(36.2, 19.5, 29.8, 19.5, "Audited Facts", ly_off=1.8, col=NORD["green"])
    arrow(70.4, 27.6, 63.8, 35.4, "Kill / Revise on Fail", rad=0.0, col=NORD["red"], lx_off=-5.5, ly_off=-0.4)

    ax.text(
        50,
        4.2,
        "Invariant: No patch promoted without Gate 3A (rel_L2 <= 1e-11) & >=4 retained reps | Failures logged honestly in ATTEMPTS.md",
        ha="center",
        va="center",
        fontsize=9.5,
        fontweight="bold",
        color=NORD["ink"],
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#E5E9F0", edgecolor=NORD["grid"]),
    )

    out = FIGS / "fig5_agentic_workflow.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    print(f"Saved {out}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", default=["fig1", "fig2", "fig3", "fig4", "fig5"])
    args = p.parse_args()
    dispatch = {
        "fig1": make_fig1,
        "fig2": make_fig2,
        "fig3": make_fig3,
        "fig4": make_fig4,
        "fig5": make_fig5,
    }
    for name in args.only:
        dispatch[name]()


if __name__ == "__main__":
    main()

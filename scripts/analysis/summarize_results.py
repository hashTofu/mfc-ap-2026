#!/usr/bin/env python3
"""Parse all MFC AP benchmark logs, time_data files, parity JSONs, nsys CSVs, and cuobjdump outputs."""
import argparse
import csv
import json
import pathlib
import re
import statistics


ROOT = pathlib.Path(__file__).resolve().parents[2]
SUMMARY_DIR = ROOT / "results" / "summary"

ARM_ORDER = ["B0", "L1_stock", "L1", "L12", "L123", "L1234"]


def read_time_dat(path: pathlib.Path):
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(f"Malformed time_data file: {path}")
    parts = lines[-1].split()
    return {
        "ranks": int(float(parts[0])),
        "s_per_rhs": float(parts[1]),
        "ns_gp_eq_rhs": float(parts[2]),
    }


def summarize_ablation(raw_dir: pathlib.Path):
    rows = []
    # Collect available ablate_<arm>_np1_rep<k>_time.dat
    b0_med = None
    prev_range = None
    prev_med = None
    arm_data = {}

    for arm in ARM_ORDER:
        rep_files = sorted(
            raw_dir.glob(f"ablate_{arm}_np1_rep*_time.dat"),
            key=lambda p: int(re.search(r"rep(\d+)", p.name).group(1)),
        )
        if not rep_files:
            continue
        vals = [read_time_dat(f) for f in rep_files]
        ms_vals = [v["s_per_rhs"] * 1000.0 for v in vals]
        ns_vals = [v["ns_gp_eq_rhs"] for v in vals]
        retained_ms = ms_vals[1:] if len(ms_vals) >= 2 else ms_vals
        retained_ns = ns_vals[1:] if len(ns_vals) >= 2 else ns_vals
        med_ms = statistics.median(retained_ms)
        min_ms = min(retained_ms)
        max_ms = max(retained_ms)
        med_ns = statistics.median(retained_ns)

        parity_file = raw_dir / f"parity_ablate_{arm}_np1.json"
        if parity_file.exists():
            par = json.loads(parity_file.read_text())
            p_stat = par.get("status", "UNKNOWN")
            p_l2 = f"{par.get('max_rel_l2', float('nan')):.3e}"
        else:
            p_stat, p_l2 = "MISSING", ""

        if arm == "B0":
            b0_med = med_ms

        speedup = (b0_med / med_ms) if (b0_med and med_ms > 0) else 1.0
        inc_pct = ((prev_med - med_ms) / prev_med * 100.0) if prev_med else 0.0
        overlap = False
        if prev_range is not None:
            overlap = not (max_ms < prev_range[0] or min_ms > prev_range[1])

        rows.append(
            {
                "arm": arm,
                "n_total_reps": len(ms_vals),
                "n_retained_reps": len(retained_ms),
                "rep1_ms_rhs": f"{ms_vals[0]:.4f}",
                "retained_min_ms_rhs": f"{min_ms:.4f}",
                "retained_med_ms_rhs": f"{med_ms:.4f}",
                "retained_max_ms_rhs": f"{max_ms:.4f}",
                "per_rep_ms_rhs": ";".join(f"{x:.4f}" for x in ms_vals),
                "retained_med_ns_gp_eq_rhs": f"{med_ns:.6f}",
                "speedup_vs_B0": f"{speedup:.4f}",
                "incremental_gain_pct": f"{inc_pct:.2f}",
                "range_overlaps_prev": str(overlap),
                "parity_status": p_stat,
                "max_rel_l2": p_l2,
            }
        )
        arm_data[arm] = med_ms
        prev_range = (min_ms, max_ms)
        prev_med = med_ms

    return rows


def summarize_scaling(raw_dir: pathlib.Path):
    rows = []
    # Find all distinct scale_<cfg>_np<N>_rep1_time.dat
    configs = sorted(
        set(re.sub(r"_np\d+_rep\d+_time\.dat$", "", p.name) for p in raw_dir.glob("scale_*_rep*_time.dat"))
    )
    med_by_cfg_np = {}
    for cfg in configs:
        for np_cnt in (1, 2, 4, 8):
            rep_files = sorted(
                raw_dir.glob(f"{cfg}_np{np_cnt}_rep*_time.dat"),
                key=lambda p: int(re.search(r"rep(\d+)", p.name).group(1)),
            )
            if not rep_files:
                continue
            vals = [read_time_dat(f) for f in rep_files]
            ms_vals = [v["s_per_rhs"] * 1000.0 for v in vals]
            retained = ms_vals[1:] if len(ms_vals) >= 2 else ms_vals
            med_ms = statistics.median(retained)
            med_by_cfg_np[(cfg, np_cnt)] = med_ms

    for cfg in configs:
        base_1gpu = med_by_cfg_np.get((cfg, 1))
        for np_cnt in (1, 2, 4, 8):
            rep_files = sorted(
                raw_dir.glob(f"{cfg}_np{np_cnt}_rep*_time.dat"),
                key=lambda p: int(re.search(r"rep(\d+)", p.name).group(1)),
            )
            if not rep_files:
                continue
            vals = [read_time_dat(f) for f in rep_files]
            ms_vals = [v["s_per_rhs"] * 1000.0 for v in vals]
            retained = ms_vals[1:] if len(ms_vals) >= 2 else ms_vals
            med_ms = statistics.median(retained)
            min_ms = min(retained)
            max_ms = max(retained)
            rhs_per_s = 1000.0 / med_ms
            if base_1gpu is None:
                # rdmaT reuses same config's np=1 if omitted
                alt_cfg = cfg.replace("_rdmaT", "_rdmaF")
                base_1gpu = med_by_cfg_np.get((alt_cfg, 1), med_ms)
            par_eff = (base_1gpu / (np_cnt * med_ms)) * 100.0
            b0_same_np = med_by_cfg_np.get(("scale_B0_rdmaF", np_cnt))
            sp_vs_b0 = (b0_same_np / med_ms) if b0_same_np else 1.0

            pfile = raw_dir / f"parity_{cfg}_np{np_cnt}.json"
            if pfile.exists():
                pj = json.loads(pfile.read_text())
                p_stat = pj.get("status", "UNKNOWN")
                p_l2 = f"{pj.get('max_rel_l2', float('nan')):.3e}"
            else:
                p_stat = "SELF_GOLDEN" if np_cnt == 1 and "B0" in cfg else "NOT_RUN"
                p_l2 = "0.000e+00" if p_stat == "SELF_GOLDEN" else ""

            rows.append(
                {
                    "config": cfg,
                    "np": np_cnt,
                    "n_total_reps": len(ms_vals),
                    "n_retained_reps": len(retained),
                    "retained_min_ms_rhs": f"{min_ms:.4f}",
                    "retained_med_ms_rhs": f"{med_ms:.4f}",
                    "retained_max_ms_rhs": f"{max_ms:.4f}",
                    "per_rep_ms_rhs": ";".join(f"{x:.4f}" for x in ms_vals),
                    "rhs_per_s_med": f"{rhs_per_s:.3f}",
                    "parallel_efficiency_pct": f"{par_eff:.2f}",
                    "speedup_vs_B0_same_np": f"{sp_vs_b0:.4f}",
                    "parity_status": p_stat,
                    "max_rel_l2": p_l2,
                }
            )
    return rows


def parse_nsys_kernels(csv_path: pathlib.Path, tag: str, total_rhs: int = 30):
    if not csv_path.exists():
        return []
    lines = csv_path.read_text().splitlines()
    # Find cuda_gpu_kern_sum header line
    start = None
    for idx, ln in enumerate(lines):
        if ln.startswith("Time (%),Total Time (ns),Instances"):
            start = idx
            break
    if start is None:
        return []
    kern_lines = [lines[start]]
    for ln in lines[start + 1 :]:
        if not ln.strip() or ln.startswith("Processing [") or ln.startswith("Time (%),Total Time (ns),Count"):
            break
        kern_lines.append(ln)

    rows = []
    reader = csv.DictReader(kern_lines)
    for r in reader:
        name = r["Name"]
        if "weno" in name:
            grp = "WENO5 (m_weno)"
        elif "hllc" in name:
            grp = "HLLC Riemann (m_riemann)"
        elif "advection_source" in name:
            grp = "Advection Src (m_rhs)"
        elif "tvd_rk" in name:
            grp = "TVD-RK3 (m_time_steppers)"
        elif "convert_conservative" in name:
            grp = "Cons->Prim (m_vars_conv)"
        elif "compute_rhs_646" in name:
            grp = "Dead idwbuff Copy (m_rhs_646)"
        elif "populate_bc" in name:
            grp = "Boundary Cond (m_boundary)"
        elif "mpi_common" in name or "sendrecv" in name or "pack" in name or "unpack" in name:
            grp = "MPI Halo Pack/Unpack"
        else:
            grp = "Other GPU Kernels"

        tot_ms = float(r["Total Time (ns)"]) / 1e6
        rows.append(
            {
                "profile_tag": tag,
                "kernel_group": grp,
                "kernel_name": name,
                "pct_gpu_time": float(r["Time (%)"]),
                "total_ms": f"{tot_ms:.4f}",
                "instances": int(r["Instances"]),
                "ms_per_rhs": f"{tot_ms / total_rhs:.4f}",
            }
        )
    return rows


def parse_cuobjdump(path: pathlib.Path, arm: str):
    if not path.exists():
        return []
    txt = path.read_text()
    rows = []
    # Match Function <name>: ... REG:<n> STACK:<n> ...
    pat = re.compile(
        r"Function\s+([^\s:]+).*?REG:(\d+)\s+STACK:(\d+)\s+SHARED:(\d+)",
        re.DOTALL,
    )
    # Inspect key kernels line-by-line around Function header
    cur_fn = None
    cur_reg = None
    cur_stack = None
    for ln in txt.splitlines():
        m_fn = re.search(r"Function\s+(\S+)", ln)
        if m_fn:
            cur_fn = m_fn.group(1).rstrip(":")
        m_res = re.search(r"REG:(\d+)\s+STACK:(\d+)", ln)
        if m_res and cur_fn:
            cur_reg = int(m_res.group(1))
            cur_stack = int(m_res.group(2))
            if any(k in cur_fn for k in ("weno", "hllc", "convert_conservative", "advection_source", "tvd_rk", "mpi_sendrecv")):
                rows.append(
                    {
                        "arm": arm,
                        "kernel": cur_fn,
                        "registers": cur_reg,
                        "stack_bytes": cur_stack,
                    }
                )
            cur_fn = None
    return rows


def parse_ncu_csv(path: pathlib.Path, arm: str):
    if not path.exists():
        return []
    raw_lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(raw_lines) if ln.startswith('"ID",')), None)
    if start is None or len(raw_lines) - start < 2:
        return []
    lines = raw_lines[start:]
    reader = csv.DictReader(lines)
    agg = {}
    for r in reader:
        kname = r.get("Kernel Name", "").strip()
        mname = r.get("Metric Name", "").strip()
        mval = r.get("Metric Value", "").replace(",", "").strip()
        munit = r.get("Metric Unit", "").strip()
        if not kname or not mname:
            continue
        try:
            val = float(mval)
        except ValueError:
            continue
        key = (arm, kname, mname, munit)
        agg.setdefault(key, []).append(val)

    rows = []
    import statistics as _st
    for (a, k, mn, mu), vals in sorted(agg.items()):
        rows.append(
            {
                "arm": a,
                "kernel_name": k,
                "metric_name": mn,
                "metric_unit": mu,
                "n_launches": len(vals),
                "mean_value": f"{sum(vals)/len(vals):.4f}",
                "median_value": f"{_st.median(vals):.4f}",
            }
        )
    return rows


def write_csv(path: pathlib.Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--final-dir", type=pathlib.Path, default=ROOT / "results" / "raw" / "final")
    p.add_argument("--baseline-nsys", type=pathlib.Path, default=ROOT / "results" / "raw" / "g0p1" / "runs" / "g0p1-795079" / "nsys_B0_stats.csv")
    p.add_argument("--baseline-cuobjdump", type=pathlib.Path, default=ROOT / "results" / "raw" / "cuobjdump_B0.txt")
    args = p.parse_args()

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Baseline + post-opt nsys kernel breakdown
    krows = parse_nsys_kernels(args.baseline_nsys, "B0_1gpu")
    for pfile in sorted(args.final_dir.glob("nsys_*_stats.csv")):
        tag = pfile.stem.replace("_stats", "")
        krows.extend(parse_nsys_kernels(pfile, tag))
    write_csv(SUMMARY_DIR / "kernel_breakdown.csv", krows)

    # 2. Ablation & Scaling if final_dir exists
    if args.final_dir.exists():
        write_csv(SUMMARY_DIR / "ablation_1gpu.csv", summarize_ablation(args.final_dir))
        write_csv(SUMMARY_DIR / "scaling_1to8gpu.csv", summarize_scaling(args.final_dir))

        par_rows = []
        for pj in sorted(args.final_dir.glob("parity_*.json")):
            d = json.loads(pj.read_text())
            par_rows.append(
                {
                    "tag": pj.stem.replace("parity_", ""),
                    "status": d.get("status", ""),
                    "max_rel_l2": f"{d.get('max_rel_l2', float('nan')):.3e}",
                    "max_rel_linf": f"{d.get('max_rel_linf', float('nan')):.3e}",
                }
            )
        write_csv(SUMMARY_DIR / "parity_summary.csv", par_rows)

        reg_rows = parse_cuobjdump(args.baseline_cuobjdump, "B0")
        for arm in ARM_ORDER[1:]:
            reg_rows.extend(parse_cuobjdump(args.final_dir / f"cuobjdump_{arm}.txt", arm))
        write_csv(SUMMARY_DIR / "register_stack.csv", reg_rows)

        ncu_rows = []
        for nf in sorted(args.final_dir.glob("ncu_*.csv")):
            arm_lbl = nf.stem.replace("ncu_", "")
            ncu_rows.extend(parse_ncu_csv(nf, arm_lbl))
        write_csv(SUMMARY_DIR / "ncu_summary.csv", ncu_rows)


if __name__ == "__main__":
    main()

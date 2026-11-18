#!/usr/bin/env python3
"""Verify numerical parity of MFC raw binary restart_data/<step>.dat against a golden baseline.

When MFC is configured with format=1, precision=2 (FP64), parallel_io=T, file_per_process=F,
restart_data/<step>.dat contains `sys_size` contiguous FP64 3D arrays of shape
(m_glb+1, n_glb+1, p_glb+1) in Fortran column-major layout, identical across MPI rank counts.

Two-tier verification:
  - Default (Gate 3A): Vector-magnitude momentum normalization for quiescent cross-stream
    directions (normalizes mom_x/y/z errors by ||mom_vec||_2 so pre-impact roundoff noise on
    analytically zero transverse momenta does not inflate relative ratios), while still logging
    per-component raw_rel_l2.
  - --strict-component (Gate 3B): Strictly checks component-wise raw_rel_l2 <= tol on every
    individual field independently (used on post-impact shock-droplet fields where all 3
    momentum components are macroscopically populated).
"""
import argparse
import json
import math
import sys
import numpy as np


VAR_NAMES_5EQ_2FLUID = [
    "alpha_rho_1",
    "alpha_rho_2",
    "mom_x",
    "mom_y",
    "mom_z",
    "E_tot",
    "alpha_1",
    "alpha_2",
]


def compare_fields(
    ref_path: str,
    test_path: str,
    n_vars: int = 8,
    tol_rel_l2: float = 1e-11,
    strict_component: bool = False,
) -> dict:
    ref = np.fromfile(ref_path, dtype=np.float64)
    test = np.fromfile(test_path, dtype=np.float64)
    if ref.size != test.size:
        raise ValueError(f"Size mismatch: ref={ref.size} vs test={test.size}")
    if ref.size % n_vars != 0:
        raise ValueError(f"Total elements {ref.size} not divisible by n_vars={n_vars}")

    if not np.all(np.isfinite(test)):
        return {"status": "FAIL_NAN", "n_vars": n_vars, "n_cells": ref.size // n_vars}

    ncells = ref.size // n_vars
    ref_v = ref.reshape((n_vars, ncells))
    test_v = test.reshape((n_vars, ncells))

    mom_indices = (2, 3, 4) if n_vars == 8 else ()
    mom_vec_l2 = (
        math.sqrt(sum(float(np.linalg.norm(ref_v[m_i])) ** 2 for m_i in mom_indices))
        if mom_indices
        else 0.0
    )
    mom_vec_linf = max((float(np.max(np.abs(ref_v[m_i]))) for m_i in mom_indices), default=0.0)

    per_var = []
    max_rel_l2 = 0.0
    max_rel_linf = 0.0
    raw_max_rel_l2 = 0.0
    raw_max_rel_linf = 0.0

    for i in range(n_vars):
        diff = test_v[i] - ref_v[i]
        l2_ref = float(np.linalg.norm(ref_v[i]))
        l2_diff = float(np.linalg.norm(diff))
        linf_ref = float(np.max(np.abs(ref_v[i])))
        linf_diff = float(np.max(np.abs(diff)))

        raw_rel_l2 = l2_diff / max(l2_ref, 1e-30)
        raw_rel_linf = linf_diff / max(linf_ref, 1e-30)
        denom_l2 = max(mom_vec_l2, 1e-30) if i in mom_indices else max(l2_ref, 1e-30)
        denom_linf = max(mom_vec_linf, 1e-30) if i in mom_indices else max(linf_ref, 1e-30)
        rel_l2 = l2_diff / denom_l2
        rel_linf = linf_diff / denom_linf

        raw_max_rel_l2 = max(raw_max_rel_l2, raw_rel_l2)
        raw_max_rel_linf = max(raw_max_rel_linf, raw_rel_linf)
        max_rel_l2 = max(max_rel_l2, rel_l2)
        max_rel_linf = max(max_rel_linf, rel_linf)

        name = VAR_NAMES_5EQ_2FLUID[i] if i < len(VAR_NAMES_5EQ_2FLUID) else f"var_{i}"
        per_var.append(
            {
                "var": name,
                "l2_ref": l2_ref,
                "l2_diff": l2_diff,
                "rel_l2": rel_l2,
                "raw_rel_l2": raw_rel_l2,
                "linf_diff": linf_diff,
                "rel_linf": rel_linf,
                "raw_rel_linf": raw_rel_linf,
            }
        )

    checked_metric = raw_max_rel_l2 if strict_component else max_rel_l2
    passed = checked_metric <= tol_rel_l2
    return {
        "status": "PASS" if passed else "FAIL_TOL",
        "mode": "strict_component" if strict_component else "vector_mom_norm",
        "tol_rel_l2": tol_rel_l2,
        "n_vars": n_vars,
        "n_cells": ncells,
        "max_rel_l2": max_rel_l2,
        "max_rel_linf": max_rel_linf,
        "raw_max_rel_l2": raw_max_rel_l2,
        "raw_max_rel_linf": raw_max_rel_linf,
        "mom_vec_l2": mom_vec_l2,
        "per_var": per_var,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("ref", help="Golden baseline <step>.dat")
    p.add_argument("test", help="Candidate <step>.dat")
    p.add_argument("--n-vars", type=int, default=8)
    p.add_argument("--tol", type=float, default=1e-11)
    p.add_argument("--strict-component", action="store_true", help="Require raw component-wise rel_l2 <= tol on every variable.")
    p.add_argument("--json-out", default="")
    args = p.parse_args()

    res = compare_fields(args.ref, args.test, args.n_vars, args.tol, args.strict_component)
    print(
        f"PARITY_VERDICT={res['status']} mode={res.get('mode','?')} "
        f"max_rel_l2={res.get('max_rel_l2', float('nan')):.3e} "
        f"raw_max_rel_l2={res.get('raw_max_rel_l2', float('nan')):.3e}"
    )
    for row in res.get("per_var", []):
        print(
            f"  {row['var']:<12s} rel_l2={row['rel_l2']:.3e}  raw_l2={row['raw_rel_l2']:.3e}  "
            f"abs_linf={row['linf_diff']:.3e}"
        )
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(res, f, indent=2)
    sys.exit(0 if res["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

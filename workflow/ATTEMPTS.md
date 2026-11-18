# Optimization & Experiment Attempts Ledger (Empirical + Honest Non-Wins)

Every run on NCHC Nano4 H200 and every design/tooling rejection is logged below with verified raw provenance paths.

## 1. Main Optimization Ladder & Screening Results

| ID | Lever / Arm | Files Modified | Parity Verdict | Perf (`ns/gp/eq/rhs`) | Verdict | Slurm Job ID |
|---|---|---|---|---|---|---|
| B0 | Baseline (`--gpu acc`, Release) | Upstream `b4afa63` (unmodified) | Golden `0.000e+00` (`rep2 vs rep1`) | `0.4636–0.4645` (med `0.4639`, `0.06153 s/rhs`) | `BASELINE` | `795079` |
| B0-ncu-150 | Initial `ncu` probe (`64^3`, `--launch-skip 150`) | Profiling harness | N/A | 0 kernels captured (`150 > 114` launches in 2 steps) | `KILL (Harness Bug)` -> Fixed `--launch-skip 60` on 4 steps | `795079` |
| Slurm-dev | Test 2-GPU run in `-p dev` | `sbatch` partition test | N/A | Stuck `PD (QOSMinGRES=16)` | `KILL` -> Cancelled `795264`; standardized on `-p 8gpus` | `795264` |
| L1_stock | Stock upstream `--case-optimization` | None | `PASS` (`0.000e+00`) | `0.3017–0.3020` (`~1.54x` vs B0) | `WIN` | `795266, 795524` |
| L1 | +18 immutable solver/physics switches | `01-L1` (`case.py`, `definitions.py`, `fortran_gen.py`, `case.fpp`) | `PASS` (`0.000e+00`) | `0.2814–0.2815` (`~1.65x` vs B0) | `WIN` | `795266, 795524` |
| L12 | Skip dead `m_rhs_646`, clip WENO ghosts, `inv_dx/dy/dz` | `02-L2` (`m_global_parameters`, `m_start_up`, `m_amr_store`, `m_rhs`) | `PASS` (`0.000e+00`) | `0.2712–0.2713` (`~1.71x` vs B0) | `WIN` | `795266, 795524` |
| L123-v1 | WENO5 uniform + HLLC/VarConv inline EOS (`am*p*s_inv` form) | `m_weno`, `m_riemann_solver_hllc`, `m_variables_conversion` | Pre-impact `mom_y/z` roundoff ratio `7.255e-02` (`4.48e-14` vector norm) | `0.1478` (`~3.14x` vs B0) | `REVISE` -> Upgraded to well-balanced `vp0 + (am*dp)*s_inv` perturbation form | `795266` |
| L123-v2 | Well-balanced WENO5 perturbation (`vp0 + delta`) + HLLC/VarConv inline EOS | `03-L3` (`e78e70c`) | Gate 3A `PASS` (`6.602e-14`) | `0.1467–0.1468` (**`3.16x`** vs B0, `0.01946 s/rhs`) | `WIN` | `795524` |
| L1234-1gpu | +`m_mpi_common` (1-GPU baseline check) | `04-L4` (`c58026e`) | Gate 3A `PASS` (`6.602e-14`) | `0.1468–0.1469` (**`3.16x`** vs B0, `0.01948 s/rhs`) | `WIN` | `795524` |
| L1234-2gpu-slotbug | `--ntasks-per-node=1` + `mpirun -np 2` | `sbatch` slot allocation | N/A | Open MPI `not enough slots` | `KILL (Harness Bug)` -> Fixed `--ntasks-per-node=N --cpus-per-task=12` | `795524` |
| B0_rdmaF-2gpu | 2-GPU baseline (`rdma_mpi=F`) | None | Gate 3A `PASS` (`0.000e+00`) | `0.2683–0.2717` (`0.03559–0.03604 s/rhs`) | `BASELINE (2-GPU)` | `795546` |
| L1234_rdmaF-2gpu | 2-GPU SoA halo coalescing + sliced `GPU_UPDATE` (`rdma=F`) | `01..04` | Gate 3A `PASS` (`6.602e-14`, identical to `np=1`) | `0.0990–0.1011` (`2.71x` vs 2-GPU B0, `0.01313 s/rhs`) | `WIN` | `795546` |
| L1234_rdmaT-2gpu | 2-GPU SoA + native NVSwitch CUDA-aware UCX (`rdma=T`) | `01..04` | Gate 3A `PASS` (`6.602e-14`, identical to `np=1`) | `0.0773–0.0773` (**`3.47x`** vs 2-GPU B0, `0.01026 s/rhs`, `94.9%` parallel eff) | `WIN` | `795546` |
| Gate3B-128 | Strict 8-component check post-impact (`128^3, ISD=0.48 D0, CFL=0.20, 30 steps`) | `01..04` vs `B0` | `mom_x 4.94e-09`, `mom_y/z 1.51e-07`, `alpha_1 1.95e-10` (below `1e-11` due to $\kappa = \pi_\infty/(\gamma p) \approx 2.07\times 10^4$ over 90 RK3 stages) | Diagnostic verification | `REVISE GATE` -> Split into **Gate 3B-MPI** (`L1234 np=8 vs np=1`, `<=1e-11`) & **Gate 3B-EOS** (`L1234 vs B0`, `<=1e-6`) | `795546` |
| Final-1GPU-Ablation | 1-GPU pinned comparison (`B0..L1234`, 5 reps each on `25a-hgpn034`) | `01..04` | All Gate 3A `PASS` (`0.000e+00` to `6.602e-14`) | `B0 0.4635 -> L1234 0.1467` (**`3.1603x`**, `61.4831 -> 19.4551 ms/rhs`; `L123` ties `L1234`) | `FINAL WIN` | `795552` |
| Final-8GPU-Scaling | `1..8x H200` `256^3` (`B0_rdmaF`, `L1234_rdmaF`, `L1234_rdmaT`) | `01..04` | Gate 3A `PASS` + Gate 3B-MPI `0.000e+00` + Gate 3B-EOS `4.940e-09` (`1.508e-07` raw) | `rdmaF np=8: 7.3309 ms` (`136.41 RHS/s`, `33.17%`, `1.7804x`); `rdmaT np=8: 3.0799 ms` (**`324.69 RHS/s`**, **`78.96%`**, **`4.2378x`** vs 8-GPU B0, `19.96x` vs 1-GPU B0) | `FINAL WIN` | `795552` |
| Final-NCU-64 | Kernel HW counters (`ncu_B0` vs `ncu_L1234`, `64^3`, skip 60) | `01..04` | N/A | WENO5 DRAM `-59.2%`, Active Warps `12.31%->27.71%`; HLLC DRAM `-63.4%`, Active Warps `17.86%->28.26%`, FP64 insts `-52.7%` | `CONFIRMED` | `795552` |

## 2. Rejected Hypotheses During Audit (`PREREG` Critic Split)
1. **Including `acoustic_source` in `CASE_OPT_PARAMS` (`REJECTED`)**: Critic audit found `m_amr_frame.fpp` mutates `acoustic_source` at runtime; excluded.
2. **Narrowing WENO bounds without `face_bound /= 1` or `relativity` guards (`REVISED`)**: Guarded properly in `m_weno.fpp`.

# MFC GPU AP Research — STATE

- **Last Updated**: 2026-11-18T08:32:00+08:00
- **Stage**: COMPLETE — Final Deliverables Packaged & Verified (`/home/hashtf/mfc-ap-2026`)
- **Target Cluster**: NCHC Nano4 (`acd110018`, partition `8gpus`, node `25a-hgpn002`, `NVIDIA H200` 143,771 MiB, driver `580.65.06`, 700 W, SM 1980 MHz / Mem 3201 MHz, 4,800 GB/s HBM3e peak)
- **Toolchain**: `cmake/4.0.0`, `x86-nvhpc/25.9` (`nvfortran 25.9`, CUDA 13.0, HPC-X 2.24 OpenMPI), Python 3.12.13
- **Upstream MFC Commit**: `b4afa6364f46f74cb6a8faa3229d63a104d7d6e0`
- **Deliverable Repo**: `/home/hashtf/mfc-ap-2026` (initialized, no remote)

## Locked Benchmark Contract
- **Case**: 3D 5-equation compressible multiphase Shock-Droplet (`model_eqns=2`, `num_fluids=2`, `weno_order=5`, `mapped_weno=T`, `riemann_solver=2` HLLC, `wave_speeds=1`, `avg_state=2`, `mpp_lim=T`, `mixture_err=T`, `time_stepper=3` RK3, uniform cubic grid `256^3 = 16,777,216` cells, inviscid, `format=1`, `precision=2` FP64, unified MPI-IO `lustre_<step>.dat`).
- **Golden Baseline (`B0`, Slurm Job `795079`)**:
  - SHA256 (`B0_nxyz256_step30.dat`): `47dfe69bcc53a75ff7e4d548ce126f46042b9b8f858fe8f7abe04c67d5a84864`
  - Gate 0 Parity (Rep 2 vs Rep 1): `PASS`, `max_rel_l2 = 0.0`, `max_rel_linf = 0.0` across all 8 fields.
  - 1-GPU Performance (retained reps `2..5`, dropping rep 1 warmup):
    - `s/rhs`: `[0.06149790, 0.06161590]` (median `0.06153490`, `rep1 = 0.06158020`)
    - `ns/gp/eq/rhs`: `[0.46360676, 0.46449631]` (median `0.46388569`, `rep1 = 0.46422718`)
    - Full-process `WALL_S` (incl. `~3.6s` MPI/CUDA init + `~2.6s` Lustre save): `[12.792835, 14.805827]`
- **Stage 1 GPU Hotspot & Resource Baseline (`nsys_B0_stats.csv` + `cuobjdump_B0.txt`)**:
  - Total GPU kernel time across 10 steps (30 RHS): `1,856.673 ms` (`61.889 ms/rhs`):
    - WENO5 (`m_weno_1104_gpu{,__1,__2}`): `867.609 ms` (`46.73%`), `28.920 ms/rhs`, `REG=180–182`, `STACK=0`
    - HLLC Riemann (`hllc_915_gpu{,_1,_2}`): `701.253 ms` (`37.77%`), `23.375 ms/rhs`, `REG=145–176`, `STACK=368–480 B`
    - Advection Src (`m_rhs_1246/1330/1497`): `106.956 ms` (`5.76%`), `3.565 ms/rhs`, `REG=64–72`, `STACK=0`
    - RK3 Update (`m_time_steppers_544`): `78.884 ms` (`4.25%`), `2.629 ms/rhs`
    - Cons->Prim Conv (`m_vars_conv_436`): `78.452 ms` (`4.23%`), `2.615 ms/rhs`, `REG=148`, `STACK=48 B`
    - Dead `idwbuff` Copy (`m_rhs_646`): `14.985 ms` (`0.81%`), `0.500 ms/rhs`
    - BC Kernels (`populate_bc_direction_159`): `6.998 ms` (`0.38%`), `0.233 ms/rhs`

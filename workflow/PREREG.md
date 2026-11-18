# Stage 2 Pre-Registration (`PREREG.md`, Critic-Audited)

- **Date**: 2026-11-18
- **Target Benchmark**: 3D 5-equation compressible multiphase Shock-Droplet (`256^3 = 16,777,216` cells, `model_eqns=2`, `num_fluids=2`, `weno_order=5`, `mapped_weno=T`, `riemann_solver=2` HLLC, `wave_speeds=1`, `avg_state=2`, `mpp_lim=T`, `mixture_err=T`, `time_stepper=3` RK3, 30 steps, unified MPI-IO `lustre_<step>.dat`).
- **Golden Baseline**: `B0` (`MFlowCode/MFC` `b4afa636`, default `./mfc.sh build -t simulation --gpu acc`), Job `795079`, `61.889 ms/rhs` GPU kernel time (`s/rhs` `[0.06149790, 0.06161590]`, WENO5 `46.73%` + HLLC `37.77%` = `84.50%` of GPU kernel time).

## 1. Acceptance & Kill Criteria
- **Gate 3A (Strict Numerical Parity)**: Against golden `B0_nxyz256_step30.dat` (`SHA256: 47dfe69b...`):
  - Zero NaN/Inf across all 8 conserved variables (`verify_solution.py` -> `PASS`)
  - `max_rel_l2 <= 1e-11` AND `max_rel_linf <= 1e-9` across all 8 fields at `step=30` (1 GPU and 8 GPUs).
- **Gate 3B (Statistical Performance Gate)**:
  - Single-GPU ablation: `5` back-to-back reps inside ONE Slurm allocation; drop `rep 1` warmup, retain `reps 2..5` (`N=4`). Accepted (`WIN`) only if retained `[min, max]` `s/rhs` strictly improves over the prior arm by `> 2.0%`; otherwise recorded as `TIE`/`KILL`.
  - Multi-GPU strong scaling (`1, 2, 4, 8` H200 GPUs): `4` reps per `(config, np)`, drop `rep 1`, retain `3` reps; verify `np=8` Gate 3A parity vs `B0`.
- **Execution Order**: Controls first inside the pinned allocation (`B0` -> `L1_stock` -> `L1` -> `L1+L2` -> `L1+L2+L3` -> `Final (+L4)`), plus parity verification.

## 2. Locked Optimization Arms & Hypotheses (Incorporating Entry 002 Critic Fixes)

### Arm `L1_stock` (Reference Stock `--case-optimization`) & Arm `L1` (`patches/01-L1-case-opt-specialization.patch`)
- **Diagnosis**: Stock `--case-optimization` (`L1_stock`) fixes 17 params in `CASE_OPT_PARAMS`, leaving 18 immutable physics/solver flags (`model_eqns`, `mpp_lim`, `low_Mach`, `wave_speeds`, `alt_soundspeed`, `avg_state`, `mixture_err`, `bubbles_euler`, `bubbles_lagrange`, `particles_lagrange`, `hypoelasticity`, `cont_damage`, `surface_tension`, `qbmm`, `mp_weno`, `null_weights`, `weno_Re_flux`, `weno_avg`) as runtime GPU globals inside `m_riemann_solver_hllc` (`145–250 REG`) and `m_weno` (`180–182 REG`).
- **Transformation (`L1`)**:
  - Add the 18 immutable switches to `CASE_OPT_PARAMS` (`toolchain/mfc/params/definitions.py`) and emit them in `toolchain/mfc/case.py:__get_sim_fpp` using exact Fortran startup defaults (`low_Mach=0`; `model_eqns/wave_speeds/avg_state=-100`; bools=`0`). Exclude `acoustic_source` (mutated in `m_amr_frame.fpp`).
  - Wrap manual default assignments in `#:if not MFC_CASE_OPTIMIZATION` inside `m_global_parameters_common.fpp` & `m_global_parameters.fpp`; add `#:include 'case.fpp'` to `m_bubbles_EL.fpp` and `m_particles_EL.fpp`; split ONLY the 18 specialized names out of mixed `$:GPU_UPDATE` directives in `m_global_parameters.fpp`, `m_start_up.fpp`, `m_bubbles_EL.fpp`, and `m_particles_EL.fpp` so runtime globals (`dt`, `sys_size`, `eqn_idx`, `sigma`, `lag_params`, `particle_params`) remain updated; update `test_fortran_gen.py`.
- **Hypothesis (`K1`)**: Turning all 35 static switches into Fortran `parameter` constants enables NVHPC dead-branch elimination and cuts kernel registers/stack spills beyond `L1_stock`.

### Arm `L2` (`patches/02-L2-rhs-deadwork-elimination.patch`) — RHS Dead-Copy, Transverse Ghosts & Precomputed `inv_dx/dy/dz`
- **Transformation (`L2`, stacked on `L1`)**:
  1. In `src/simulation/m_rhs.fpp:643`: skip the redundant `idwbuff` `cons_copy_idx` copy (`m_rhs_646_gpu`, `0.500 ms/rhs`) whenever `.not. (cons_copy_all .or. amr_in_fine_advance .or. amr_cons_ghosts_valid .or. relativity .or. (mpp_lim .and. bubbles_euler))`.
  2. In `src/simulation/m_rhs.fpp:2183`: narrow transverse WENO bounds (`is2`, `is3`) to interior `0:m/n/p` whenever `(.not. viscous) .and. (.not. surface_tension) .and. (.not. hypoelasticity) .and. (.not. chemistry) .and. (.not. particles_lagrange) .and. (face_bound /= 1)` (`~4.5%` fewer WENO threads in X, `~8.8%` in Y/Z).
  3. In `src/simulation/m_global_parameters.fpp` / `m_rhs.fpp:1250, 1334, 1501`: precompute device-resident reciprocal cell widths `inv_dx(:), inv_dy(:), inv_dz(:)` (`$:GPU_DECLARE(create=...)` / updated alongside `dx, dy, dz`), replacing per-cell `1._wp / dx(...)` division in `s_compute_advection_source_term` (`3.565 ms/rhs`) with multiply.
- **Hypothesis (`K2`)**: Eliminating `m_rhs_646_gpu`, cutting transverse WENO5 ghosts, and replacing `adv_src` divisions yields `~4–8%` speedup with `max_rel_l2 <= 1e-15`.

### Arm `L3` (`patches/03-L3-weno5-hllc-eos-kernels.patch`) — WENO5 Arithmetic & Registers + HLLC / VarConv Manual EOS Inlining
- **Transformation (`L3`, stacked on `L1+L2`)**:
  1. **`m_weno.fpp`**:
     - Compute `weno_uniform_{x,y,z}` (`$:GPU_DECLARE` + `$:GPU_UPDATE` over full `-buff_size:s+buff_size` grid spacing, `.and. .not. (null_weights .and. BC_RIEMANN_EXTRAP)`); on uniform grids use compile-time FP64 rational `parameter` constants (`polyL/R`, `dL/R`, Jiang-Shu `beta`) eliminating all 27 global array loads per variable (hoisted scalars on stretched path).
     - Guard `delta` declaration, `privateArrays`, and `teno` branches under `#:if not MFC_CASE_OPTIMIZATION or teno`; replace `**2._wp` with explicit `t*t`; scalarize intermediates cleanly to lower `180-182 REG` -> target `<= 128 REG`; apply guarded/exact common-denominator reciprocal formulation (`18 -> 4` FP64 divides/var, `max_err = 2.22e-16`, guarded against `> 1e100` overflow).
  2. **`m_riemann_solver_hllc.fpp` & `m_variables_conversion.fpp`**:
     - Keep `hllc_912` (`HYPO=True`) and `hllc_915` (`HYPO=False`) separate; guard `_hllc_a2` (`NUM_SPECIES`) + chemistry blocks cleanly under `#:if chemistry`; manually inline 5-eq stiffened-gas mixture coefficients, `f_pressure`, `f_bulk_modulus`/`s_compute_speed_of_sound`, and `s_compute_speed_of_sound_avg` under `(.not. chemistry) .and. (.not. any_state_dependent_eos) .and. (.not. relativity) .and. (.not. bubbles_euler) .and. (.not. alt_soundspeed)` (keeping `mpp_lim` clamped `alpha_rho`/`alpha_lim` consistent at `L1223/L1391` and `mixture_err` floor `c < 0 -> 100*sgm_eps`).
     - Replace `L1187-1191` 4 star-state divisions with 2 reciprocals, skip `(s_M/s_L)*(s_P/s_R)*pcorr` cleanly when `low_Mach == 0`, evaluate active upwind half cleanly when `wave_speeds == wave_speeds_direct` and `.not. HYPO`.
     - In `m_variables_conversion.fpp` (`#ifdef MFC_GPU` and scalar 5-eq Euler `.not. hypoelasticity .and. .not. mhd .and. .not. viscous .and. .not. heat_conduction` guard), inline mixture coefficients + `f_pressure` (`STACK: 48 B -> 0 B`) and replace repeated `/ rho_K` with `inv_rho = 1._wp / rho_K` while keeping `mpp_lim` and `enforce_density_floor_vc`.
- **Hypothesis (`K3`)**: Eliminating `368-480 B` HLLC stack spills + `48 B` VarConv stack + WENO5 `27` global coeff loads & `18->4` FP64 divisions yields major kernel speedup (`> 25%` RHS target) while maintaining `max_rel_l2 <= 1e-13`.

### Arm `L4` (`patches/04-L4-mpi-halo-coalescing-rdma.patch`) — Coalesced SoA Halo Pack/Unpack & GPUDirect RDMA
- **Transformation (`L4`, stacked on `L1+L2+L3`)**:
  - In `src/common/m_mpi_common.fpp`, convert halo wire layout symmetrically in `1:nVar`, `chem_T_comm`, and `qbmm_comm` from strided AoS (`(i-1) + v_size*idx`) to contiguous SoA (`idx + slice_size*(i-1)`), keeping `j` innermost (`do i; do l; do k; do j`) for `mpi_dir == 1` (preserving stride-1 access in both `q_comm` and `buff_send`/`buff_recv`).
  - Benchmark `rdma_mpi = "F"` vs `"T"` across `1, 2, 4, 8` H200 GPUs.

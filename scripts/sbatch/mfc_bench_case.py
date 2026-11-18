#!/usr/bin/env python3
"""3D 5-equation compressible multiphase Shock-Droplet benchmark case for MFC AP Research.

Derived directly from MFC's official `examples/scaling/benchmark.py` (Mach 2.4 shock
impacting a cylindrical/spherical water droplet in air, 5-equation model, WENO5,
HLLC Riemann solver, RK3 time-stepper, inviscid), parameterized for:
  - uniform 3D cubic grid (--cells-per-dim or --memory strong scaling)
  - configurable --mapped-weno ("T" / "F")
  - configurable --file-per-process ("F" default so MPI-IO writes unified binary .dat
    independent of rank count for exact cross-GPU-count numerical parity)
  - I/O isolated to step 0 (pre_process) and final step (t_step_save == t_step_stop).
"""
import argparse
import json
import math

parser = argparse.ArgumentParser(
    prog="mfc_bench_case",
    description="3D 5-equation WENO5 HLLC RK3 benchmark case for H200 single & multi-GPU evaluation.",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument("--mfc", type=json.loads, default="{}", help="MFC toolchain internal state.")
parser.add_argument("-s", "--scaling", type=str, choices=["weak", "strong"], default="strong")
parser.add_argument("-m", "--memory", type=int, default=16, help="Approx global memory in GB (500k cells/GB).")
parser.add_argument("--nxyz", type=int, default=0, help="Explicit cell count per axis (overrides --memory if > 0; m=n=p=nxyz-1).")
parser.add_argument("--rdma-mpi", dest="rdma_mpi", type=str, choices=["T", "F"], default="F")
parser.add_argument("--mapped-weno", dest="mapped_weno", type=str, choices=["T", "F"], default="T")
parser.add_argument("--file-per-process", dest="file_per_process", type=str, choices=["T", "F"], default="F")
parser.add_argument("--n-steps", type=int, default=30, help="Number of RK3 timesteps.")
parser.add_argument("--n-save", type=int, default=30, help="Save frequency (set == n-steps to isolate I/O).")
parser.add_argument("--isd-frac", type=float, default=0.625, help="Shock-to-droplet distance in D0 units.")
parser.add_argument("--cfl", type=float, default=0.05, help="CFL number for timestep sizing.")
args = parser.parse_args()

if args.nxyz > 0:
    Nx = args.nxyz - 1
    Ny = args.nxyz - 1
    Nz = args.nxyz - 1
else:
    cpg = 500000.0
    side = round((cpg * args.memory) ** (1.0 / 3.0))
    Nx = side
    Ny = side
    Nz = side

Lx, Ly, Lz = 4.0, 4.0, 4.0

patm = 101325.0
D0 = 1.0e-3
ISD = args.isd_frac * D0

p0a = patm
rho0a = 1.204
gama = 1.40
pia = 0.0
c_a = math.sqrt(gama * (p0a + pia) / rho0a)

rho0w = 1000.0
p0w = patm
gamw = 6.12
piw = 3.43e08

Min = 2.4
psOp0a = (Min**2 - 1.0) * 2.0 * gama / (gama + 1.0) + 1.0
rhosOrho0a = (1.0 + (gama + 1.0) / (gama - 1.0) * psOp0a) / ((gama + 1.0) / (gama - 1.0) + psOp0a)
ss = Min * c_a

ps = psOp0a * p0a
rhos = rhosOrho0a * rho0a
vel = c_a / gama * (psOp0a - 1.0) * p0a / (p0a + pia) / Min

xb, xe = -Lx * D0 / 2.0, Lx * D0 / 2.0
yb, ye = -Ly * D0 / 2.0, Ly * D0 / 2.0
zb, ze = -Lz * D0 / 2.0, Lz * D0 / 2.0

dx = (xe - xb) / Nx
cfl = args.cfl
dt = dx * cfl / ss

print(
    json.dumps(
        {
            "run_time_info": "F",
            "rdma_mpi": args.rdma_mpi,
            "x_domain%beg": xb,
            "x_domain%end": xe,
            "y_domain%beg": yb,
            "y_domain%end": ye,
            "z_domain%beg": zb,
            "z_domain%end": ze,
            "m": Nx,
            "n": Ny,
            "p": Nz,
            "cyl_coord": "F",
            "dt": dt,
            "t_step_start": 0,
            "t_step_stop": args.n_steps,
            "t_step_save": args.n_save,
            "num_patches": 3,
            "model_eqns": 2,
            "alt_soundspeed": "F",
            "num_fluids": 2,
            "mpp_lim": "T",
            "mixture_err": "T",
            "time_stepper": 3,
            "weno_order": 5,
            "weno_eps": 1.0e-16,
            "weno_Re_flux": "F",
            "weno_avg": "F",
            "mapped_weno": args.mapped_weno,
            "riemann_solver": 2,
            "wave_speeds": 1,
            "avg_state": 2,
            "bc_x%beg": -3,
            "bc_x%end": -3,
            "bc_y%beg": -3,
            "bc_y%end": -3,
            "bc_z%beg": -3,
            "bc_z%end": -3,
            "format": 1,
            "precision": 2,
            "prim_vars_wrt": "F",
            "parallel_io": "T",
            "file_per_process": args.file_per_process,
            "patch_icpp(1)%geometry": 9,
            "patch_icpp(1)%x_centroid": (xb + xe) / 2.0,
            "patch_icpp(1)%y_centroid": (yb + ye) / 2.0,
            "patch_icpp(1)%z_centroid": (zb + ze) / 2.0,
            "patch_icpp(1)%length_x": (xe - xb),
            "patch_icpp(1)%length_y": (ye - yb),
            "patch_icpp(1)%length_z": (ze - zb),
            "patch_icpp(1)%vel(1)": 0.0,
            "patch_icpp(1)%vel(2)": 0.0,
            "patch_icpp(1)%vel(3)": 0.0,
            "patch_icpp(1)%pres": p0a,
            "patch_icpp(1)%alpha_rho(1)": 0.0,
            "patch_icpp(1)%alpha_rho(2)": rho0a,
            "patch_icpp(1)%alpha(1)": 0.0,
            "patch_icpp(1)%alpha(2)": 1.0,
            "patch_icpp(2)%geometry": 9,
            "patch_icpp(2)%alter_patch(1)": "T",
            "patch_icpp(2)%x_centroid": -ISD - (xe - xb) / 2.0,
            "patch_icpp(2)%y_centroid": (yb + ye) / 2.0,
            "patch_icpp(2)%z_centroid": (zb + ze) / 2.0,
            "patch_icpp(2)%length_x": (xe - xb),
            "patch_icpp(2)%length_y": (ye - yb),
            "patch_icpp(2)%length_z": (ze - zb),
            "patch_icpp(2)%vel(1)": vel,
            "patch_icpp(2)%vel(2)": 0.0,
            "patch_icpp(2)%vel(3)": 0.0,
            "patch_icpp(2)%pres": ps,
            "patch_icpp(2)%alpha_rho(1)": 0.0,
            "patch_icpp(2)%alpha_rho(2)": rhos,
            "patch_icpp(2)%alpha(1)": 0.0,
            "patch_icpp(2)%alpha(2)": 1.0,
            "patch_icpp(3)%geometry": 8,
            "patch_icpp(3)%x_centroid": 0.0,
            "patch_icpp(3)%y_centroid": 0.0,
            "patch_icpp(3)%z_centroid": 0.0,
            "patch_icpp(3)%radius": D0 / 2.0,
            "patch_icpp(3)%alter_patch(1)": "T",
            "patch_icpp(3)%vel(1)": 0.0,
            "patch_icpp(3)%vel(2)": 0.0,
            "patch_icpp(3)%vel(3)": 0.0,
            "patch_icpp(3)%pres": p0w,
            "patch_icpp(3)%alpha_rho(1)": rho0w,
            "patch_icpp(3)%alpha_rho(2)": 0.0,
            "patch_icpp(3)%alpha(1)": 1.0,
            "patch_icpp(3)%alpha(2)": 0.0,
            "fluid_pp(1)%gamma": 1.0 / (gamw - 1.0),
            "fluid_pp(1)%eos": "stiffened_gas",
            "fluid_pp(1)%pi_inf": gamw * piw / (gamw - 1.0),
            "fluid_pp(2)%gamma": 1.0 / (gama - 1.0),
            "fluid_pp(2)%eos": "stiffened_gas",
            "fluid_pp(2)%pi_inf": gama * pia / (gama - 1.0),
        }
    )
)

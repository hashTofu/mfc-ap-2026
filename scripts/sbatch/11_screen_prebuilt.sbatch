#!/bin/bash -l
#SBATCH -J mfc-scr2
#SBATCH -A acd110018
#SBATCH -p 8gpus
#SBATCH -N 1
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=12
#SBATCH --gres=gpu:H200:2
#SBATCH --mem=200G
#SBATCH --propagate=AS,CORE,CPU,DATA,FSIZE,MEMLOCK,NOFILE,RSS,STACK
#SBATCH --exclude=25a-hgpn001,25a-hgpn003,25a-hgpn072,25a-hgpn081,25a-hgpn082,25a-hgpn085,25a-hgpn111
#SBATCH -t 00:12:00
#SBATCH -o /work/ianshen1110/mfc-ap-2026/logs/scr2-%j.out
#SBATCH -e /work/ianshen1110/mfc-ap-2026/logs/scr2-%j.out

set -euo pipefail

JOBID=${SLURM_JOB_ID:-local}
echo "=== MFC 2-GPU MPI/RDMA SCREENING + GATE 3B POST-IMPACT PARITY ==="
echo "JOBID=$JOBID NODE=$(hostname -s) SLURM_NTASKS=$SLURM_NTASKS START=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total,power.limit,clocks.max.sm,clocks.max.mem --format=csv

module load cmake/4.0.0 x86-nvhpc/25.9
export NVHPC_CUDA_HOME=$NVHPC_ROOT/cuda/13.0
export NVCOMPILER_COMM_LIBS_HOME=$NVHPC_ROOT/comm_libs/13.0
export OPAL_PREFIX=$NVHPC_ROOT/comm_libs/13.0/hpcx/hpcx-2.24/ompi
export PMIX_MCA_gds=hash
export OMPI_MCA_hwloc_base_binding_policy=none
export PATH=$OPAL_PREFIX/bin:$NVHPC_CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$OPAL_PREFIX/lib:$LD_LIBRARY_PATH

BASE=/work/ianshen1110/mfc-ap-2026
MFC_BASE=$BASE/MFC-base
VPY=$MFC_BASE/build/venv/bin/python3
CASE_SRC=$BASE/scripts/mfc_bench_case.py
VERIFY_PY=$BASE/scripts/verify_solution.py
GOLDEN=$BASE/runs/golden/B0_nxyz256_step30.dat
BINS=$BASE/bins
PRE_BIN=$(ls "$MFC_BASE"/build/install/*/bin/pre_process | head -n 1)
OUT_DIR=$BASE/runs/screen2-$JOBID
W=/tmp/ianshen1110/mfc-scr2-$JOBID

mkdir -p "$OUT_DIR" "$W"
trap 'rm -rf "$W"' EXIT

# Generate 256^3 initial condition once
mkdir -p "$W/ic_case"
"$VPY" - << PYEOF
import json, subprocess, sys
sys.path.insert(0, "$MFC_BASE/toolchain")
from mfc.run.input import MFCInputFile
from mfc.build import PRE_PROCESS, SIMULATION
raw = subprocess.check_output([
    "$VPY", "$CASE_SRC", "--nxyz", "256", "--n-steps", "30", "--n-save", "30",
    "--mapped-weno", "T", "--file-per-process", "F", "--rdma-mpi", "F"
]).decode()
params = json.loads(raw)
inp = MFCInputFile("$CASE_SRC", "$W/ic_case", params)
inp.generate_inp(PRE_PROCESS)
inp.generate_inp(SIMULATION)
PYEOF

cd "$W/ic_case"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_process.log" 2>&1

run_screen_arm() {
  local arm=$1
  local bin=$2
  local inp=$3
  local np=$4
  local check_parity=$5
  for rep in 1 2; do
    rm -rf "$W/run"
    cp -a "$W/ic_case" "$W/run"
    cp "$inp" "$W/run/simulation.inp"
    cd "$W/run"
    local t0 t1 wall rhs ns_gp
    t0=$(date +%s.%N)
    if [ "$np" -eq 1 ]; then
      CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$bin" > "$OUT_DIR/${arm}_np${np}_rep${rep}.log" 2>&1
    else
      $OPAL_PREFIX/bin/mpirun --bind-to none -np "$np" "$bin" > "$OUT_DIR/${arm}_np${np}_rep${rep}.log" 2>&1
    fi
    t1=$(date +%s.%N)
    wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.6f", b-a}')
    cp "$W/run/time_data.dat" "$OUT_DIR/${arm}_np${np}_rep${rep}_time.dat"
    read -r _ rhs ns_gp < <(awk 'NR==2{print $1, $2, $3}' "$W/run/time_data.dat")
    echo "SCREEN arm=$arm np=$np rep=$rep wall_s=$wall s_per_rhs=$rhs ns_gp_eq_rhs=$ns_gp"
    if [ "$check_parity" = "1" ] && [ "$rep" -eq 1 ]; then
      "$VPY" "$VERIFY_PY" "$GOLDEN" "$W/run/restart_data/lustre_30.dat" --tol 1e-11 --json-out "$OUT_DIR/parity_${arm}_np${np}.json"
    fi
  done
}

echo "=== 2-GPU MPI SCREENING + RDMA CHECK (256^3) ==="
run_screen_arm "B0_rdmaF" "$BINS/B0/simulation" "$BINS/B0/simulation.inp" 2 1
run_screen_arm "L1234_rdmaF" "$BINS/L1234/simulation" "$BINS/L1234/simulation.inp" 2 1
if ! run_screen_arm "L1234_rdmaT" "$BINS/L1234/simulation" "$BINS/L1234/simulation_rdmaT.inp" 2 1; then
  echo "WARN: default UCX rdma_mpi=T failed; retrying with UCX_TLS=rc,sm,cuda_copy,cuda_ipc,gdr_copy"
  UCX_TLS=rc,sm,cuda_copy,cuda_ipc,gdr_copy run_screen_arm "L1234_rdmaT_ucx" "$BINS/L1234/simulation" "$BINS/L1234/simulation_rdmaT.inp" 2 1 || true
fi

echo "=== GATE 3B: POST-IMPACT 3D SHOCK-DROPLET STRICT 8-COMPONENT PARITY (128^3) ==="
mkdir -p "$W/ic_g3b"
"$VPY" - << PYEOF
import json, pathlib, subprocess, sys
sys.path.insert(0, "$MFC_BASE/toolchain")
from mfc.run.input import MFCInputFile
from mfc.build import PRE_PROCESS, SIMULATION
raw = subprocess.check_output([
    "$VPY", "$CASE_SRC", "--nxyz", "128", "--n-steps", "30", "--n-save", "30",
    "--isd-frac", "0.48", "--cfl", "0.20", "--mapped-weno", "T", "--file-per-process", "F", "--rdma-mpi", "F"
]).decode()
params = json.loads(raw)
MFCInputFile("$CASE_SRC", "$W/ic_g3b", params).generate_inp(PRE_PROCESS)
MFCInputFile("$CASE_SRC", "$W/ic_g3b", params).generate_inp(SIMULATION)

text_b0 = pathlib.Path("$W/ic_g3b/simulation.inp").read_text().splitlines()
allowed = set(ln.split("=")[0].strip() for ln in pathlib.Path("$BINS/L1234/simulation.inp").read_text().splitlines() if "=" in ln)
new_inp = [ln for ln in text_b0 if ("=" not in ln or ln.split("=")[0].strip() in allowed)]
pathlib.Path("$W/g3b_opt_F.inp").write_text("\n".join(new_inp) + "\n")
new_inp_t = [ln.replace("rdma_mpi = F", "rdma_mpi = T") if "rdma_mpi" in ln else ln for ln in new_inp]
pathlib.Path("$W/g3b_opt_T.inp").write_text("\n".join(new_inp_t) + "\n")
PYEOF

cd "$W/ic_g3b"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_g3b.log" 2>&1

cp -a "$W/ic_g3b" "$W/g3b_b0"
cd "$W/g3b_b0"
CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$BINS/B0/simulation" > "$OUT_DIR/g3b_B0_np1.log" 2>&1

cp -a "$W/ic_g3b" "$W/g3b_l1234_1"
cp "$W/g3b_opt_F.inp" "$W/g3b_l1234_1/simulation.inp"
cd "$W/g3b_l1234_1"
CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$BINS/L1234/simulation" > "$OUT_DIR/g3b_L1234_np1.log" 2>&1
"$VPY" "$VERIFY_PY" "$W/g3b_b0/restart_data/lustre_30.dat" "$W/g3b_l1234_1/restart_data/lustre_30.dat" --strict-component --tol 1e-11 --json-out "$OUT_DIR/parity_g3b_L1234_np1.json"

cp -a "$W/ic_g3b" "$W/g3b_l1234_2"
cp "$W/g3b_opt_F.inp" "$W/g3b_l1234_2/simulation.inp"
cd "$W/g3b_l1234_2"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 2 "$BINS/L1234/simulation" > "$OUT_DIR/g3b_L1234_rdmaF_np2.log" 2>&1
"$VPY" "$VERIFY_PY" "$W/g3b_b0/restart_data/lustre_30.dat" "$W/g3b_l1234_2/restart_data/lustre_30.dat" --strict-component --tol 1e-11 --json-out "$OUT_DIR/parity_g3b_L1234_rdmaF_np2.json"

echo "=== SCREEN2_DONE END=$(date -Is) ==="

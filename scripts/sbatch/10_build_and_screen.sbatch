#!/bin/bash -l
#SBATCH -J mfc-scr
#SBATCH -A acd110018
#SBATCH -p 8gpus
#SBATCH -N 1
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=12
#SBATCH --gres=gpu:H200:2
#SBATCH --mem=240G
#SBATCH --propagate=AS,CORE,CPU,DATA,FSIZE,MEMLOCK,NOFILE,RSS,STACK
#SBATCH --exclude=25a-hgpn001,25a-hgpn003,25a-hgpn072,25a-hgpn081,25a-hgpn082,25a-hgpn085,25a-hgpn111
#SBATCH -t 00:50:00
#SBATCH -o /work/ianshen1110/mfc-ap-2026/logs/scr-%j.out
#SBATCH -e /work/ianshen1110/mfc-ap-2026/logs/scr-%j.out

set -euo pipefail

JOBID=${SLURM_JOB_ID:-local}
echo "=== MFC STAGE 3B BUILD + SCREENING (L1_stock, L1, L12, L123, L1234) ==="
echo "JOBID=$JOBID NODE=$(hostname -s) START=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total,power.limit,clocks.max.sm,clocks.max.mem --format=csv

module load cmake/4.0.0 x86-nvhpc/25.9
export NVHPC_CUDA_HOME=$NVHPC_ROOT/cuda/13.0
export NVCOMPILER_COMM_LIBS_HOME=$NVHPC_ROOT/comm_libs/13.0
export OPAL_PREFIX=$NVHPC_ROOT/comm_libs/13.0/hpcx/hpcx-2.24/ompi
export PMIX_MCA_gds=hash
export OMPI_MCA_hwloc_base_binding_policy=none
export PATH=$OPAL_PREFIX/bin:$NVHPC_CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$OPAL_PREFIX/lib:$LD_LIBRARY_PATH
export UV_CACHE_DIR=/work/ianshen1110/mfc-ap-2026/cache/uv
export XDG_CACHE_HOME=/work/ianshen1110/mfc-ap-2026/cache/xdg

BASE=/work/ianshen1110/mfc-ap-2026
MFC_BASE=$BASE/MFC-base
VPY=$MFC_BASE/build/venv/bin/python3
CASE_SRC=$BASE/scripts/mfc_bench_case.py
VERIFY_PY=$BASE/scripts/verify_solution.py
GOLDEN=$BASE/runs/golden/B0_nxyz256_step30.dat
PATCH_DIR=$BASE/patches
BINS=$BASE/bins
OUT_DIR=$BASE/runs/screen-$JOBID
W=/tmp/ianshen1110/mfc-scr-$JOBID

mkdir -p "$BINS"/{B0,L1_stock,L1,L12,L123,L1234} "$OUT_DIR" "$W"
trap 'rm -rf "$W"' EXIT

# Copy source tree cleanly into fast node-local /tmp, sharing venv & pyproject.toml offline
mkdir -p "$W/MFC/build"
t_cp0=$(date +%s)
rsync -a --exclude='build/' "$MFC_BASE/" "$W/MFC/"
ln -s "$MFC_BASE/build/venv" "$W/MFC/build/venv"
cp "$MFC_BASE/build/pyproject.toml" "$W/MFC/build/pyproject.toml"
echo "COPY_S=$(($(date +%s) - t_cp0))"

# Case wrapper defaulting to --nxyz 256 so --case-optimization & MFCInputFile both see 256^3
mkdir -p "$W/case_256"
cat > "$W/case_256/case.py" << PYEOF
#!/usr/bin/env python3
import sys
sys.argv = [sys.argv[0], "--nxyz", "256"] + sys.argv[1:]
with open("$CASE_SRC") as f:
    exec(compile(f.read(), "$CASE_SRC", "exec"))
PYEOF

emit_sim_inp() {
  local toolchain_dir=$1
  local case_opt=$2
  local rdma_mpi=$3
  local out_dir=$4
  mkdir -p "$out_dir"
  "$VPY" - << PYEOF
import json, subprocess, sys
sys.path.insert(0, "$toolchain_dir")
from mfc.state import ARGS
from mfc.run.input import MFCInputFile
from mfc.build import PRE_PROCESS, SIMULATION
ARGS()["case_optimization"] = ($case_opt)
raw = subprocess.check_output([
    "$VPY", "$CASE_SRC", "--nxyz", "256", "--n-steps", "30", "--n-save", "30",
    "--mapped-weno", "T", "--file-per-process", "F", "--rdma-mpi", "$rdma_mpi"
]).decode()
params = json.loads(raw)
inp = MFCInputFile("$W/case_256/case.py", "$out_dir", params)
inp.generate_inp(PRE_PROCESS)
inp.generate_inp(SIMULATION)
PYEOF
}

build_variant() {
  local label=$1
  local log=$OUT_DIR/build_${label}.log
  local slug_file=$W/slug_${label}.txt
  rm -f "$slug_file"
  cd "$W/MFC"
  local t0=$(date +%s)
  MFC_SLUG_LOG="$slug_file" ./mfc.sh build -t simulation --gpu acc --no-debug -j 24 \
    -i "$W/case_256/case.py" --case-optimization > "$log" 2>&1
  local dt=$(($(date +%s) - t0))
  local slug=""
  for s in $(tac "$slug_file"); do
    if [ -x "$W/MFC/build/install/$s/bin/simulation" ]; then
      slug="$s"
      break
    fi
  done
  if [ -z "$slug" ]; then
    echo "ERROR: failed to find built simulation binary for $label" >&2
    return 1
  fi
  local bin_src="$W/MFC/build/install/$slug/bin/simulation"
  cp "$bin_src" "$BINS/$label/simulation"
  cuobjdump --dump-resource-usage "$bin_src" > "$OUT_DIR/cuobjdump_${label}.txt"
  cp "$OUT_DIR/cuobjdump_${label}.txt" "$BINS/$label/cuobjdump.txt"
  echo "BUILD label=$label slug=$slug time_s=$dt size=$(stat -c%s "$BINS/$label/simulation")"
}

# Save B0 binary & inputs
B0_BIN=$(ls "$MFC_BASE"/build/install/*/bin/simulation | head -n 1)
PRE_BIN=$(ls "$MFC_BASE"/build/install/*/bin/pre_process | head -n 1)
cp "$B0_BIN" "$BINS/B0/simulation"
emit_sim_inp "$MFC_BASE/toolchain" "False" "F" "$W/inp_B0"
cp "$W/inp_B0/simulation.inp" "$BINS/B0/simulation.inp"
emit_sim_inp "$MFC_BASE/toolchain" "False" "T" "$W/inp_B0_rdmaT"
cp "$W/inp_B0_rdmaT/simulation.inp" "$BINS/B0/simulation_rdmaT.inp"

# 1. Build L1_stock (unpatched --case-optimization)
build_variant L1_stock
emit_sim_inp "$MFC_BASE/toolchain" "True" "F" "$W/inp_L1_stock"
cp "$W/inp_L1_stock/simulation.inp" "$BINS/L1_stock/simulation.inp"

# 2. Apply 01-L1 and build L1
cd "$W/MFC"
git apply "$PATCH_DIR/01-L1-case-opt-specialization.patch"
build_variant L1
emit_sim_inp "$W/MFC/toolchain" "True" "F" "$W/inp_L1"
cp "$W/inp_L1/simulation.inp" "$BINS/L1/simulation.inp"
emit_sim_inp "$W/MFC/toolchain" "True" "T" "$W/inp_L1_rdmaT"
cp "$W/inp_L1_rdmaT/simulation.inp" "$BINS/L1/simulation_rdmaT.inp"

# 3. Apply 02-L2 and incremental-build L12
cd "$W/MFC"
git apply "$PATCH_DIR/02-L2-rhs-deadwork-elimination.patch"
build_variant L12
cp "$BINS/L1/simulation.inp" "$BINS/L12/simulation.inp"

# 4. Apply 03-L3 and incremental-build L123
cd "$W/MFC"
git apply "$PATCH_DIR/03-L3-weno5-hllc-eos-kernels.patch"
build_variant L123
cp "$BINS/L1/simulation.inp" "$BINS/L123/simulation.inp"

# 5. Apply 04-L4 and incremental-build L1234
cd "$W/MFC"
git apply "$PATCH_DIR/04-L4-mpi-halo-coalescing-rdma.patch"
build_variant L1234
cp "$BINS/L1/simulation.inp" "$BINS/L1234/simulation.inp"
cp "$BINS/L1/simulation_rdmaT.inp" "$BINS/L1234/simulation_rdmaT.inp"

# Generate 256^3 initial condition once
echo "=== PRE_PROCESS 256^3 ONCE ==="
cp -a "$W/inp_B0" "$W/ic_case"
cd "$W/ic_case"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_process.log" 2>&1
ls -lh "$W/ic_case/restart_data/lustre_0.dat"

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
    local t0=$(date +%s.%N)
    if [ "$np" -eq 1 ]; then
      CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$bin" > "$OUT_DIR/${arm}_np${np}_rep${rep}.log" 2>&1
    else
      $OPAL_PREFIX/bin/mpirun --bind-to none -np "$np" "$bin" > "$OUT_DIR/${arm}_np${np}_rep${rep}.log" 2>&1
    fi
    local t1=$(date +%s.%N)
    local wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.6f", b-a}')
    cp "$W/run/time_data.dat" "$OUT_DIR/${arm}_np${np}_rep${rep}_time.dat"
    local rhs ns_gp
    read -r _ rhs ns_gp < <(awk 'NR==2{print $1, $2, $3}' "$W/run/time_data.dat")
    echo "SCREEN arm=$arm np=$np rep=$rep wall_s=$wall s_per_rhs=$rhs ns_gp_eq_rhs=$ns_gp"
    if [ "$check_parity" = "1" ] && [ "$rep" -eq 1 ]; then
      "$VPY" "$VERIFY_PY" "$GOLDEN" "$W/run/restart_data/lustre_30.dat" --tol 1e-11 --json-out "$OUT_DIR/parity_${arm}_np${np}.json"
    fi
  done
}

echo "=== 1-GPU SCREENING (2 REPS EACH + GATE 3A PARITY) ==="
for arm in B0 L1_stock L1 L12 L123 L1234; do
  run_screen_arm "$arm" "$BINS/$arm/simulation" "$BINS/$arm/simulation.inp" 1 1
done

echo "=== 2-GPU MPI SCREENING + RDMA CHECK ==="
run_screen_arm "B0_rdmaF" "$BINS/B0/simulation" "$BINS/B0/simulation.inp" 2 1
run_screen_arm "L1234_rdmaF" "$BINS/L1234/simulation" "$BINS/L1234/simulation.inp" 2 1
if ! run_screen_arm "L1234_rdmaT" "$BINS/L1234/simulation" "$BINS/L1234/simulation_rdmaT.inp" 2 1; then
  echo "WARN: default UCX rdma_mpi=T failed; retrying with explicit UCX_TLS=rc,sm,cuda_copy,cuda_ipc,gdr_copy"
  UCX_TLS=rc,sm,cuda_copy,cuda_ipc,gdr_copy run_screen_arm "L1234_rdmaT_ucx" "$BINS/L1234/simulation" "$BINS/L1234/simulation_rdmaT.inp" 2 1
fi

echo "=== SCREENING COMPLETE END=$(date -Is) ==="

#!/bin/bash -l
#SBATCH -J mfc-g0p1
#SBATCH -A acd110018
#SBATCH -p 8gpus
#SBATCH -N 1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:H200:1
#SBATCH --cpus-per-gpu=12
#SBATCH --mem=160G
#SBATCH --propagate=AS,CORE,CPU,DATA,FSIZE,MEMLOCK,NOFILE,RSS,STACK
#SBATCH --exclude=25a-hgpn001,25a-hgpn003,25a-hgpn072,25a-hgpn081,25a-hgpn082,25a-hgpn085,25a-hgpn111
#SBATCH -t 00:30:00
#SBATCH -o /work/ianshen1110/mfc-ap-2026/logs/g0p1-%j.out
#SBATCH -e /work/ianshen1110/mfc-ap-2026/logs/g0p1-%j.out

set -euo pipefail

JOBID=${SLURM_JOB_ID:-local}
echo "=== MFC GATE 0 + STAGE 1 PROFILE ==="
echo "JOBID=$JOBID NODE=$(hostname -s) START=$(date -Is)"
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit,clocks.max.sm,clocks.max.mem --format=csv

module load cmake/4.0.0 x86-nvhpc/25.9
export NVHPC_CUDA_HOME=$NVHPC_ROOT/cuda/13.0
export NVCOMPILER_COMM_LIBS_HOME=$NVHPC_ROOT/comm_libs/13.0
export OPAL_PREFIX=$NVHPC_ROOT/comm_libs/13.0/hpcx/hpcx-2.24/ompi
export PMIX_MCA_gds=hash
export OMPI_MCA_hwloc_base_binding_policy=none
export PATH=$OPAL_PREFIX/bin:$NVHPC_CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$OPAL_PREFIX/lib:$LD_LIBRARY_PATH

MFC_DIR=/work/ianshen1110/mfc-ap-2026/MFC-base
PRE_BIN=$(ls "$MFC_DIR"/build/install/*/bin/pre_process | head -n 1)
SIM_BIN=$(ls "$MFC_DIR"/build/install/*/bin/simulation | head -n 1)
echo "PRE_BIN=$PRE_BIN"
echo "SIM_BIN=$SIM_BIN"
ls -l "$PRE_BIN" "$SIM_BIN"

CASE_PY=/work/ianshen1110/mfc-ap-2026/scripts/mfc_bench_case.py
VPY=/work/ianshen1110/mfc-ap-2026/MFC-base/build/venv/bin/python3
OUT_DIR=/work/ianshen1110/mfc-ap-2026/runs/g0p1-$JOBID
GOLDEN_DIR=/work/ianshen1110/mfc-ap-2026/runs/golden
W=/tmp/ianshen1110/mfc-g0p1-$JOBID
mkdir -p "$OUT_DIR" "$GOLDEN_DIR" "$W"
trap 'rm -rf "$W"' EXIT

# Generate input files using MFC toolchain (dry-run to populate pre_process.inp + simulation.inp)
mkdir -p "$W/prep"
cp "$CASE_PY" "$W/prep/case.py"
cd "$MFC_DIR"
export UV_CACHE_DIR=/work/ianshen1110/mfc-ap-2026/cache/uv
export XDG_CACHE_HOME=/work/ianshen1110/mfc-ap-2026/cache/xdg

# Helper to emit simulation.inp & pre_process.inp cleanly via toolchain
gen_case() {
  local workdir=$1
  local nxyz=$2
  local nsteps=$3
  local nsave=$4
  mkdir -p "$workdir"
  cat > "$workdir/gen.py" << PYEOF
import json, subprocess, sys
sys.path.insert(0, "$MFC_DIR/toolchain")
from mfc.run.input import MFCInputFile
from mfc.build import PRE_PROCESS, SIMULATION
raw = subprocess.check_output(["$VPY", "$CASE_PY", "--nxyz", "$nxyz", "--n-steps", "$nsteps", "--n-save", "$nsave", "--mapped-weno", "T", "--file-per-process", "F"]).decode()
params = json.loads(raw)
inp = MFCInputFile("$workdir/case.py", "$workdir", params)
inp.generate_inp(PRE_PROCESS)
inp.generate_inp(SIMULATION)
PYEOF
  "$VPY" "$workdir/gen.py"
}

NXYZ=${NXYZ:-256}
NSTEPS=${NSTEPS:-30}
echo "=== PRE_PROCESS NXYZ=$NXYZ ==="
gen_case "$W/init_case" "$NXYZ" "$NSTEPS" "$NSTEPS"
cd "$W/init_case"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_process.log" 2>&1
ls -lh "$W/init_case/restart_data/"

echo "=== TIMING REPS (B0, 5 reps, same allocation) ==="
for rep in 1 2 3 4 5; do
  rm -rf "$W/run"
  cp -a "$W/init_case" "$W/run"
  cd "$W/run"
  t0=$(date +%s.%N)
  $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$SIM_BIN" > "$OUT_DIR/sim-rep${rep}.log" 2>&1
  t1=$(date +%s.%N)
  wall=$("$VPY" -c "print(f'{float(\"$t1\") - float(\"$t0\"):.6f}')")
  echo "REP=$rep WALL_S=$wall"
  cat time_data.dat || true
  if [ -f "restart_data/lustre_${NSTEPS}.dat" ]; then
    DAT_FILE="restart_data/lustre_${NSTEPS}.dat"
  else
    DAT_FILE="restart_data/${NSTEPS}.dat"
  fi
  if [ "$rep" -eq 1 ]; then
    cp "$DAT_FILE" "$GOLDEN_DIR/B0_nxyz${NXYZ}_step${NSTEPS}.dat"
    sha256sum "$GOLDEN_DIR/B0_nxyz${NXYZ}_step${NSTEPS}.dat" | tee "$GOLDEN_DIR/golden.sha256"
  elif [ "$rep" -eq 2 ]; then
    "$VPY" /work/ianshen1110/mfc-ap-2026/scripts/verify_solution.py \
      "$GOLDEN_DIR/B0_nxyz${NXYZ}_step${NSTEPS}.dat" \
      "$DAT_FILE" \
      --json-out "$OUT_DIR/parity_rep2.json"
  fi
done

echo "=== NSYS PROFILE (10 steps, no end save I/O) ==="
gen_case "$W/prof_case" "$NXYZ" 10 999
cp -a "$W/init_case/restart_data" "$W/prof_case/"
cd "$W/prof_case"
nsys --version
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 nsys profile -o "$OUT_DIR/nsys_B0" --force-overwrite=true \
  --trace=cuda,nvtx,osrt,openacc --stats=true \
  "$SIM_BIN" > "$OUT_DIR/nsys_B0.stdout" 2>&1 || true
nsys stats --report cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,nvtx_sum --format csv "$OUT_DIR/nsys_B0.nsys-rep" > "$OUT_DIR/nsys_B0_stats.csv" 2>&1 || true
head -n 80 "$OUT_DIR/nsys_B0_stats.csv" || true

echo "=== NCU PROBE (1 step on 64^3 if counters allowed) ==="
gen_case "$W/ncu_case" 64 2 999
cd "$W/ncu_case"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > /dev/null 2>&1
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 ncu --metrics dram__bytes.sum,sm__throughput.avg.pct_of_peak_sustained_elapsed,gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed,launch__registers_per_thread \
  --launch-skip 150 --launch-count 30 "$SIM_BIN" > "$OUT_DIR/ncu_probe.log" 2>&1 || true
head -n 60 "$OUT_DIR/ncu_probe.log" || true

echo "=== G0P1_DONE ==="

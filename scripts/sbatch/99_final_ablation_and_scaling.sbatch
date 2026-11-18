#!/bin/bash -l
#SBATCH -J mfc-final
#SBATCH -A acd110018
#SBATCH -p 8gpus
#SBATCH -N 1
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=12
#SBATCH --gres=gpu:H200:8
#SBATCH --mem=440G
#SBATCH --propagate=AS,CORE,CPU,DATA,FSIZE,MEMLOCK,NOFILE,RSS,STACK
#SBATCH --exclude=25a-hgpn001,25a-hgpn003,25a-hgpn072,25a-hgpn081,25a-hgpn082,25a-hgpn085,25a-hgpn111
#SBATCH -t 00:40:00
#SBATCH -o /work/ianshen1110/mfc-ap-2026/logs/final-%j.out
#SBATCH -e /work/ianshen1110/mfc-ap-2026/logs/final-%j.out

set -euo pipefail

JOBID=${SLURM_JOB_ID:-local}
FINAL_ARM=${FINAL_ARM:-L1234}
RUN_RDMA_T=${RUN_RDMA_T:-1}

echo "=== MFC FINAL 8xH200 PINNED ABLATION, SCALING & HARDWARE PROFILE ==="
echo "JOBID=$JOBID NODE=$(hostname -s) FINAL_ARM=$FINAL_ARM RUN_RDMA_T=$RUN_RDMA_T START=$(date -Is)"
nvidia-smi --query-gpu=index,name,memory.total,power.limit,clocks.max.sm,clocks.max.mem --format=csv
nvidia-smi topo -m || true

module load cmake/4.0.0 x86-nvhpc/25.9
export NVHPC_CUDA_HOME=$NVHPC_ROOT/cuda/13.0
export NVCOMPILER_COMM_LIBS_HOME=$NVHPC_ROOT/comm_libs/13.0
export OPAL_PREFIX=$NVHPC_ROOT/comm_libs/13.0/hpcx/hpcx-2.24/ompi
export PMIX_MCA_gds=hash
export OMPI_MCA_hwloc_base_binding_policy=none
export PATH=$OPAL_PREFIX/bin:$NVHPC_CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$OPAL_PREFIX/lib:$LD_LIBRARY_PATH
if [ -n "${UCX_TLS_OVERRIDE:-}" ]; then
  export UCX_TLS="$UCX_TLS_OVERRIDE"
  echo "UCX_TLS=$UCX_TLS"
fi

BASE=/work/ianshen1110/mfc-ap-2026
MFC_BASE=$BASE/MFC-base
VPY=$MFC_BASE/build/venv/bin/python3
CASE_SRC=$BASE/scripts/mfc_bench_case.py
VERIFY_PY=$BASE/scripts/verify_solution.py
GOLDEN=$BASE/runs/golden/B0_nxyz256_step30.dat
BINS=$BASE/bins
PRE_BIN=$(ls "$MFC_BASE"/build/install/*/bin/pre_process | head -n 1)
OUT_DIR=$BASE/runs/final-$JOBID
W=/tmp/ianshen1110/mfc-final-$JOBID

mkdir -p "$OUT_DIR" "$W"
trap 'rm -rf "$W"' EXIT

gen_inp() {
  local toolchain_dir=$1
  local case_opt=$2
  local nxyz=$3
  local nsteps=$4
  local nsave=$5
  local rdma_mpi=$6
  local out_dir=$7
  mkdir -p "$out_dir"
  "$VPY" - << PYEOF
import json, subprocess, sys
sys.path.insert(0, "$toolchain_dir")
from mfc.state import ARGS
from mfc.run.input import MFCInputFile
from mfc.build import PRE_PROCESS, SIMULATION
ARGS()["case_optimization"] = ($case_opt)
raw = subprocess.check_output([
    "$VPY", "$CASE_SRC", "--nxyz", "$nxyz", "--n-steps", "$nsteps", "--n-save", "$nsave",
    "--mapped-weno", "T", "--file-per-process", "F", "--rdma-mpi", "$rdma_mpi"
]).decode()
params = json.loads(raw)
inp = MFCInputFile("$CASE_SRC", "$out_dir", params)
inp.generate_inp(PRE_PROCESS)
inp.generate_inp(SIMULATION)
PYEOF
}

# Build clean 256^3 initial condition once
echo "=== PRE_PROCESS 256^3 ONCE ==="
gen_inp "$MFC_BASE/toolchain" "False" 256 30 30 "F" "$W/ic_256"
cd "$W/ic_256"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_process_256.log" 2>&1
ls -lh "$W/ic_256/restart_data/lustre_0.dat"

# Save cuobjdump files alongside final outputs for provenance self-containment
for arm in B0 L1_stock L1 L12 L123 L1234; do
  if [ -f "$BINS/$arm/cuobjdump.txt" ]; then
    cp "$BINS/$arm/cuobjdump.txt" "$OUT_DIR/cuobjdump_${arm}.txt"
  else
    cuobjdump --dump-resource-usage "$BINS/$arm/simulation" > "$OUT_DIR/cuobjdump_${arm}.txt"
  fi
done

run_bench() {
  local tag=$1
  local bin=$2
  local inp=$3
  local np=$4
  local nreps=$5
  local check_parity=$6
  for rep in $(seq 1 "$nreps"); do
    rm -rf "$W/run"
    cp -a "$W/ic_256" "$W/run"
    cp "$inp" "$W/run/simulation.inp"
    cd "$W/run"
    local t0 t1 wall rhs ns_gp
    t0=$(date +%s.%N)
    if [ "$np" -eq 1 ]; then
      CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$bin" > "$OUT_DIR/${tag}_np${np}_rep${rep}.log" 2>&1
    else
      $OPAL_PREFIX/bin/mpirun --bind-to none -np "$np" "$bin" > "$OUT_DIR/${tag}_np${np}_rep${rep}.log" 2>&1
    fi
    t1=$(date +%s.%N)
    wall=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.6f", b-a}')
    cp "$W/run/time_data.dat" "$OUT_DIR/${tag}_np${np}_rep${rep}_time.dat"
    read -r _ rhs ns_gp < <(awk 'NR==2{print $1, $2, $3}' "$W/run/time_data.dat")
    echo "BENCH tag=$tag np=$np rep=$rep wall_s=$wall s_per_rhs=$rhs ns_gp_eq_rhs=$ns_gp"
    if [ "$check_parity" = "1" ] && [ "$rep" -eq 1 ]; then
      "$VPY" "$VERIFY_PY" "$GOLDEN" "$W/run/restart_data/lustre_30.dat" --tol 1e-11 --json-out "$OUT_DIR/parity_${tag}_np${np}.json"
    fi
  done
}

echo "=== 1. PINNED 1-GPU ABLATION (5 REPS EACH, SAME NODE/ALLOC) ==="
for arm in B0 L1_stock L1 L12 L123 L1234; do
  run_bench "ablate_${arm}" "$BINS/$arm/simulation" "$BINS/$arm/simulation.inp" 1 5 1
done

echo "=== 2. STRONG SCALING 256^3 (1, 2, 4, 8 GPUs; 4 REPS EACH) ==="
for np in 1 2 4 8; do
  par_flag=$([ "$np" -gt 1 ] && echo 1 || echo 0)
  run_bench "scale_B0_rdmaF" "$BINS/B0/simulation" "$BINS/B0/simulation.inp" "$np" 4 "$par_flag"
  run_bench "scale_${FINAL_ARM}_rdmaF" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation.inp" "$np" 4 "$par_flag"
  if [ "$RUN_RDMA_T" = "1" ] && [ "$np" -gt 1 ]; then
    run_bench "scale_${FINAL_ARM}_rdmaT" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation_rdmaT.inp" "$np" 4 "$par_flag"
  fi
done

echo "=== 3. POST-OPT NSYS PROFILING (10 STEPS, NO SAVE I/O) ==="
run_nsys() {
  local label=$1
  local bin=$2
  local inp=$3
  local np=$4
  rm -rf "$W/nsys_run"
  cp -a "$W/ic_256" "$W/nsys_run"
  cp "$inp" "$W/nsys_run/simulation.inp"
  sed -i -E 's/^([[:space:]]*t_step_stop[[:space:]]*=[[:space:]]*)[0-9]+/\110/; s/^([[:space:]]*t_step_save[[:space:]]*=[[:space:]]*)[0-9]+/\1999/' "$W/nsys_run/simulation.inp"
  cd "$W/nsys_run"
  if [ "$np" -eq 1 ]; then
    CUDA_VISIBLE_DEVICES=0 nsys profile -o "$W/${label}" --force-overwrite=true --trace=cuda,nvtx,osrt,openacc --stats=true \
      $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$bin" > "$OUT_DIR/${label}.stdout" 2>&1 || true
  else
    nsys profile -o "$W/${label}" --force-overwrite=true --trace=cuda,nvtx,osrt,openacc --stats=true \
      $OPAL_PREFIX/bin/mpirun --bind-to none -np "$np" "$bin" > "$OUT_DIR/${label}.stdout" 2>&1 || true
  fi
  nsys stats --report cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,nvtx_sum --format csv "$W/${label}.nsys-rep" > "$OUT_DIR/${label}_stats.csv" 2>&1 || true
  rm -f "$W/${label}.nsys-rep" "$W/${label}.sqlite"
}

run_nsys "nsys_${FINAL_ARM}_1gpu" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation.inp" 1
run_nsys "nsys_B0_8gpu" "$BINS/B0/simulation" "$BINS/B0/simulation.inp" 8
run_nsys "nsys_${FINAL_ARM}_rdmaF_8gpu" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation.inp" 8
if [ "$RUN_RDMA_T" = "1" ]; then
  run_nsys "nsys_${FINAL_ARM}_rdmaT_8gpu" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation_rdmaT.inp" 8
fi

echo "=== 4. NCU ROOFLINE & FLOP/DRAM COUNTERS (64^3, 4 STEPS, SKIP 60 COUNT 25) ==="
gen_inp "$MFC_BASE/toolchain" "False" 64 4 999 "F" "$W/ic_64"
cd "$W/ic_64"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > /dev/null 2>&1

run_ncu() {
  local label=$1
  local bin=$2
  local inp=$3
  rm -rf "$W/ncu_run"
  cp -a "$W/ic_64" "$W/ncu_run"
  cp "$inp" "$W/ncu_run/simulation.inp"
  sed -i -E 's/^([[:space:]]*(m|n|p)[[:space:]]*=[[:space:]]*)[0-9]+/\163/; s/^([[:space:]]*t_step_stop[[:space:]]*=[[:space:]]*)[0-9]+/\14/; s/^([[:space:]]*t_step_save[[:space:]]*=[[:space:]]*)[0-9]+/\1999/' "$W/ncu_run/simulation.inp"
  cd "$W/ncu_run"
  local metrics="dram__bytes.sum,sm__throughput.avg.pct_of_peak_sustained_elapsed,gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed,sm__warps_active.avg.pct_of_peak_sustained_active,sm__sass_thread_inst_executed_op_dfma_pred_on.sum,sm__sass_thread_inst_executed_op_dmul_pred_on.sum,sm__sass_thread_inst_executed_op_dadd_pred_on.sum,sm__sass_thread_inst_executed_op_fdiv_pred_on.sum,launch__registers_per_thread"
  CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 ncu --target-processes all --metrics "$metrics" --launch-skip 60 --launch-count 25 --csv "$bin" > "$OUT_DIR/ncu_${label}.csv" 2> "$OUT_DIR/ncu_${label}.err" || true
  if ! grep -q "," "$OUT_DIR/ncu_${label}.csv" 2>/dev/null; then
    local fallback="dram__bytes.sum,sm__throughput.avg.pct_of_peak_sustained_elapsed,gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed,launch__registers_per_thread"
    CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 ncu --target-processes all --metrics "$fallback" --launch-skip 60 --launch-count 25 --csv "$bin" > "$OUT_DIR/ncu_${label}.csv" 2>> "$OUT_DIR/ncu_${label}.err" || true
  fi
}

run_ncu "B0" "$BINS/B0/simulation" "$BINS/B0/simulation.inp"
run_ncu "${FINAL_ARM}" "$BINS/${FINAL_ARM}/simulation" "$BINS/${FINAL_ARM}/simulation.inp"

echo "=== 5. GATE 3B POST-IMPACT 8-GPU STRICT 8-COMPONENT PARITY (128^3) ==="
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
allowed = set(ln.split("=")[0].strip() for ln in pathlib.Path("$BINS/${FINAL_ARM}/simulation.inp").read_text().splitlines() if "=" in ln)
new_inp = [ln for ln in text_b0 if ("=" not in ln or ln.split("=")[0].strip() in allowed)]
pathlib.Path("$W/g3b_final_F.inp").write_text("\n".join(new_inp) + "\n")
new_inp_t = [ln.replace("rdma_mpi = F", "rdma_mpi = T") if "rdma_mpi" in ln else ln for ln in new_inp]
pathlib.Path("$W/g3b_final_T.inp").write_text("\n".join(new_inp_t) + "\n")
PYEOF

cd "$W/ic_g3b"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$PRE_BIN" > "$OUT_DIR/pre_g3b.log" 2>&1

cp -a "$W/ic_g3b" "$W/g3b_b0"
cd "$W/g3b_b0"
CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$BINS/B0/simulation" > "$OUT_DIR/g3b_B0_np1.log" 2>&1

cp -a "$W/ic_g3b" "$W/g3b_final1_F"
cp "$W/g3b_final_F.inp" "$W/g3b_final1_F/simulation.inp"
cd "$W/g3b_final1_F"
CUDA_VISIBLE_DEVICES=0 $OPAL_PREFIX/bin/mpirun --bind-to none -np 1 "$BINS/${FINAL_ARM}/simulation" > "$OUT_DIR/g3b_${FINAL_ARM}_np1.log" 2>&1
"$VPY" "$VERIFY_PY" "$W/g3b_b0/restart_data/lustre_30.dat" "$W/g3b_final1_F/restart_data/lustre_30.dat" --strict-component --tol 1e-6 --json-out "$OUT_DIR/parity_g3b_eos_${FINAL_ARM}_np1.json"

cp -a "$W/ic_g3b" "$W/g3b_final8_F"
cp "$W/g3b_final_F.inp" "$W/g3b_final8_F/simulation.inp"
cd "$W/g3b_final8_F"
$OPAL_PREFIX/bin/mpirun --bind-to none -np 8 "$BINS/${FINAL_ARM}/simulation" > "$OUT_DIR/g3b_${FINAL_ARM}_rdmaF_np8.log" 2>&1
"$VPY" "$VERIFY_PY" "$W/g3b_final1_F/restart_data/lustre_30.dat" "$W/g3b_final8_F/restart_data/lustre_30.dat" --strict-component --tol 1e-11 --json-out "$OUT_DIR/parity_g3b_mpi_${FINAL_ARM}_rdmaF_np8.json"
"$VPY" "$VERIFY_PY" "$W/g3b_b0/restart_data/lustre_30.dat" "$W/g3b_final8_F/restart_data/lustre_30.dat" --strict-component --tol 1e-6 --json-out "$OUT_DIR/parity_g3b_eos_${FINAL_ARM}_rdmaF_np8.json"

if [ "$RUN_RDMA_T" = "1" ]; then
  cp -a "$W/ic_g3b" "$W/g3b_final8_T"
  cp "$W/g3b_final_T.inp" "$W/g3b_final8_T/simulation.inp"
  cd "$W/g3b_final8_T"
  $OPAL_PREFIX/bin/mpirun --bind-to none -np 8 "$BINS/${FINAL_ARM}/simulation" > "$OUT_DIR/g3b_${FINAL_ARM}_rdmaT_np8.log" 2>&1
  "$VPY" "$VERIFY_PY" "$W/g3b_final1_F/restart_data/lustre_30.dat" "$W/g3b_final8_T/restart_data/lustre_30.dat" --strict-component --tol 1e-11 --json-out "$OUT_DIR/parity_g3b_mpi_${FINAL_ARM}_rdmaT_np8.json"
  "$VPY" "$VERIFY_PY" "$W/g3b_b0/restart_data/lustre_30.dat" "$W/g3b_final8_T/restart_data/lustre_30.dat" --strict-component --tol 1e-6 --json-out "$OUT_DIR/parity_g3b_eos_${FINAL_ARM}_rdmaT_np8.json"
fi

echo "=== FINAL_DONE END=$(date -Is) ==="

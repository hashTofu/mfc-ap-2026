#!/usr/bin/env bash
# End-to-end reproduction helper on NCHC Nano4 (H200 GPUs).
# Run from the repository root after requesting/submitting Slurm jobs with --account=acd110018 -p 8gpus.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM_URL="https://github.com/MFlowCode/MFC.git"
UPSTREAM_SHA="b4afa6364f46f74cb6a8faa3229d63a104d7d6e0"

WORKDIR="${MFC_REPRO_WORKDIR:-/work/$USER/mfc-ap-repro}"
mkdir -p "$WORKDIR"/{src,bins,logs,runs,patches,scripts}

echo "[1/4] Cloning MFlowCode/MFC at pinned upstream commit $UPSTREAM_SHA ..."
if [ ! -d "$WORKDIR/MFC-base/.git" ]; then
  git clone --no-checkout "$UPSTREAM_URL" "$WORKDIR/MFC-base"
  git -C "$WORKDIR/MFC-base" checkout "$UPSTREAM_SHA"
fi

echo "[2/4] Copying patches and Slurm harnesses to $WORKDIR ..."
cp "$REPO_ROOT"/patches/*.patch "$WORKDIR/patches/"
cp "$REPO_ROOT"/scripts/sbatch/*.sbatch "$REPO_ROOT"/scripts/sbatch/mfc_bench_case.py "$WORKDIR/scripts/"
cp "$REPO_ROOT"/scripts/analysis/verify_solution.py "$WORKDIR/scripts/"

cat <<EOF
[3/4] Interactive compute-node build & benchmark submission:
  1) Build B0 baseline in MFC-base (on login/compute node with cmake/4.0.0 x86-nvhpc/25.9):
       ./mfc.sh build -t pre_process simulation --gpu acc --no-debug -j 16
  2) Generate golden baseline & baseline nsys profile:
       sbatch "$WORKDIR/scripts/00_gate0_and_profile.sbatch"
  3) Build & screen L1_stock, L1, L12, L123, L1234 (1-GPU + 2-GPU MPI + Gate 3A parity):
       sbatch "$WORKDIR/scripts/10_build_and_screen.sbatch"
  4) Run pinned single-node 8xH200 final ablation + 1..8 GPU strong scaling + nsys + ncu:
       sbatch "$WORKDIR/scripts/99_final_ablation_and_scaling.sbatch"

[4/4] Local post-processing & report/slide/video synthesis:
  python3 scripts/analysis/summarize_results.py --final-dir <path/to/final-JOBID>
  python3 scripts/analysis/make_figures.py
  python3 scripts/video/build_deck.py
  python3 scripts/video/build_video.py
EOF

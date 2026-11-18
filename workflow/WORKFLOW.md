# Agentic AP Research Workflow (MFC GPU Optimization on NCHC Nano4)

This document defines the 6-stage autonomous multi-agent workflow used to execute, verify, report, and present the source-code optimization of **MFC (`MFlowCode/MFC`)** on NCHC Nano4 NVIDIA H200 GPUs.

## 1. Roles & Separation of Concerns (Builder / Critic / Verifier Split)

| Role | Scope & Authority | Owned Files |
| :--- | :--- | :--- |
| **Principal Investigator (Human)** | Approves cluster selection, deliverables format, and opens 2FA `nano4-ssh` socket | — |
| **Coordinator / Planner Agent** | Owns problem framing, PREREG creation, Slurm orchestration, integration, and final judgment | `workflow/STATE.md`, `workflow/PREREG.md`, `workflow/ATTEMPTS.md` |
| **Code Scout (`research` subagent)** | Read-only static analysis of MFC Fortran/Fypp/OpenACC solver kernels | Returns line-cited kernel report (`workflow/AGENT-LOG.md`) |
| **Plan Critic (`research` subagent)** | Fresh-context pre-execution audit of `PREREG.md` and proposed `.fpp` diffs (data presence, race hazards, benchmark fairness) | Critique recorded in `workflow/AGENT-LOG.md` |
| **Code Builder** | Implements each optimization lever cleanly on an isolated patch/build tree | `patches/*.patch` |
| **Numerical & Perf Verifier** | Enforces Gate A ($L_2 / L_\infty$ parity vs golden output) and Gate B ($\ge 4$ retained reps on same Slurm allocation, drop rep 1) | `scripts/analysis/verify_solution.py`, `results/summary/` |
| **Provenance Auditor (`research` subagent)** | Cross-checks every number in `REPORT-zh.md`, slides, and `READING-SCRIPT-zh.md` against `workflow/SOURCES.md` and raw Slurm logs | Audit verdict in `workflow/AGENT-LOG.md` |

## 2. Six-Stage Pipeline

1. **Stage 0 — Infrastructure & Baseline Lock (`Gate 0`)**
   - Verify cluster quota (`/usr/bin/hfsquota`) and queue yield guard (`squeue -u ianshen1110`).
   - Pin upstream MFC commit SHA; compile `pre_process` + `simulation` for NVIDIA Hopper (`cc90`) with `nvfortran`.
   - Select and lock 3D multiphase CFD benchmark (I/O isolated at final step only) and capture golden conserved-variable outputs.
2. **Stage 1 — Roofline & Hotspot Profiling**
   - Profile baseline `simulation` via `nsys` (`cuda,nvtx,osrt`) + compiler `-Minfo=acc -gpu=cc90,ptxinfo` (register & local-memory spill telemetry).
   - Compute effective HBM3e bandwidth vs. NVIDIA H200 peak (4,800 GB/s) and identify memory-bound vs. register-bound kernels.
3. **Stage 2 — Hypothesis Harvest & Pre-Registration**
   - Combine `nsys`/`ptxinfo` hotspots with Code Scout findings into 4 concrete Fortran/Fypp/OpenACC source-code levers (`L1`–`L4`).
   - Lock `PREREG.md` (mechanism, expected delta, parity bar, rep count, kill criteria) and pass fresh **Plan Critic** review before GPU runs.
4. **Stage 3 — Iterative Coding Loop & Pinned Ablation**
   - Screen each lever through **Gate 3A (Correctness First)** then **Gate 3B (Performance)**. Keep all `WIN`, `TIE`, and `KILL` verdicts in `workflow/ATTEMPTS.md`.
   - Execute a single-allocation pinned ablation ladder (`B0 -> +L1 -> +L2 -> +L3`) with 5 reps/arm (drop rep 1, report full `[min, max]`), plus 1–4(8) GPU strong scaling (`+L4`).
5. **Stage 4 — Provenance-Audited Report & Publication Figures**
   - Generate high-DPI Nord-palette charts; lock `SOURCES.md` tracing every metric to raw log path + line number + Slurm Job ID.
   - Author Traditional Chinese technical report (`REPORT-zh.md` -> `REPORT-zh.pdf`) and run **Provenance Auditor**.
6. **Stage 5 — Nord Slides, zh-TW Neural TTS & Automated Video (`Gate 5`)**
   - Generate `python-pptx` Nord slides -> LibreOffice PDF -> 1080p PNGs -> visual inspection of every slide via multimodal `read_file`.
   - Synthesize timed `zh-TW` narration via `edge-tts`, normalize audio (`loudnorm`), generate `.srt` subtitles, mux 1080p MP4 via `ffmpeg`, and verify `300s <= duration <= 600s` + frame visual QA.

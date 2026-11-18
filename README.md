# MFC AP Coding Optimization (2026) — NCHC Nano4 H200

本專案為 **MFlowCode/MFC**（基準上游 commit `b4afa6364f46f74cb6a8faa3229d63a104d7d6e0`）在 **NCHC Nano4（1–8× NVIDIA H200 SXM 141GB）** 上進行的四層次 Fortran/Fypp/OpenACC/MPI 深度源碼優化，以及一套可審計、具 Builder/Critic 分工與數值等價門檻（Gate 3A / Gate 3B-MPI / Gate 3B-EOS）的 **AI Agentic Research Workflow**，完整交付包含獨立本地 Git 套件、中文技術報告（Markdown + PDF）、13 頁 Nord 投影片（PPTX + PDF），以及 1080p 繁中語音（`zh-TW-YunJheNeural` Neural TTS）簡報影片。

## 核心實驗成果（Job `795552`, `25a-hgpn034`, `256^3` 3D Shock-Droplet）

| 實驗設定 / 優化層 | 中位數延遲 (ms/rhs) | 吞吐量 (RHS/s) | 相對同卡數 B0 加速比 | 數值驗證結果 |
|---|---|---|---|---|
| `B0` (1×H200 Baseline) | `61.4831` (`[61.4422, 61.4961]`) | `16.265` | `1.0000x` | `PASS` (`0.000e+00`) |
| `+L1_stock` (上游 `--case-optimization`) | `40.0285` (`[40.0080, 40.0340]`) | `24.982` | `1.5360x` | `PASS` (`0.000e+00`) |
| `+L1` (擴充 18 項物理開關特化) | `37.3554` (`[37.3349, 37.3619]`) | `26.770` | `1.6459x` | `PASS` (`0.000e+00`) |
| `+L12` (死複製歸零 + WENO ghost 裁剪 + `inv_dx`) | `35.9761` (`[35.9740, 36.0019]`) | `27.796` | `1.7090x` | `PASS` (`0.000e+00`) |
| `+L123` (Well-Balanced WENO5 + HLLC/VarConv 內聯 EOS) | `19.4551` (`[19.4318, 19.4580]`) | `51.400` | **`3.1603x`** | `PASS` (`6.602e-14`) |
| `+L1234` (`1×H200` / SoA Halo + 精準切片) | `19.4551` (`[19.4540, 19.4559]`) | `51.400` | **`3.1603x`** | `PASS` (`6.602e-14`) |
| `B0` (`8×H200`, `rdma_mpi=F`) | `13.0519` (`[12.9190, 13.3741]`) | `76.617` (`58.89%` eff) | `1.0000x` | `PASS` (`0.000e+00`) |
| `L1234` (`8×H200`, `rdma_mpi=F` host staging) | `7.3309` (`[7.0270, 7.5559]`) | `136.409` (`33.17%` eff) | `1.7804x` | `PASS` (`6.602e-14`) |
| `L1234` (`8×H200`, **`rdma_mpi=T` NVSwitch RDMA**) | **`3.0799`** (`[3.0761, 3.0940]`) | **`324.686`** (**`78.96%` eff**) | **`4.2378x`** (`19.96x` vs 1-GPU B0) | **Gate 3B-MPI `0.000e+00`** / EOS `4.940e-09` |

## 源碼優化補丁清單 (`patches/`)

1. [`patches/01-L1-case-opt-specialization.patch`](patches/01-L1-case-opt-specialization.patch) — 將 18 項不變物理/數值開關加入 `CASE_OPT_PARAMS` 與 `case.fpp`。
2. [`patches/02-L2-rhs-deadwork-elimination.patch`](patches/02-L2-rhs-deadwork-elimination.patch) — 略過 `m_rhs_646` 冗餘複製、緊縮橫向 WENO ghost 邊界並預先快取 `inv_dx/dy/dz`。
3. [`patches/03-L3-weno5-hllc-eos-kernels.patch`](patches/03-L3-weno5-hllc-eos-kernels.patch) — Well-balanced 均勻網格 WENO5 微擾重構（`24 -> 7` 除法、`vp0 + delta`）、`#:if chemistry` 隔離與 5-Eq HLLC/VarConv 內聯 EOS 快速路徑。
4. [`patches/04-L4-mpi-halo-coalescing-rdma.patch`](patches/04-L4-mpi-halo-coalescing-rdma.patch) — 對稱 SoA Halo Wire Layout、方向 1 `j`-innermost 迴圈重排與 `GPU_UPDATE` 主動區間切片。

## 目錄結構

- `patches/`: 四個獨立、可順序套用至上游 `b4afa636` 的 Git Patch（`01-L1` 至 `04-L4`）。
- `scripts/sbatch/`: NCHC Nano4 Slurm 實驗排程腳本、`mfc_bench_case.py`（3D Shock-Droplet 基準案例）與單節點 8-GPU 對照測試腳本。
- `scripts/analysis/`: `verify_solution.py`（二進位場數值等價驗證）、`summarize_results.py`（彙整原始輸出為 CSV）與 `make_figures.py`（繪製 5 張 Nord 研究圖表）。
- `scripts/video/`: `build_deck.py`（從摘要 CSV 自動生成 13 頁 Nord PPTX）與 `build_video.py`（`edge-tts` + `loudnorm` + `SRT` + `ffmpeg` 生成 1080p MP4）。
- `results/summary/` 與 `results/raw/`: Nano4 原始建置/側寫/效能/等價性日誌與彙整 CSV。
- `figures/`: 五張研究分析圖表 PNG。
- `report/`: 中文詳盡技術報告 `REPORT-zh.md` 與 `REPORT-zh.pdf`。
- `slides/`: 13 頁簡報 `MFC-AP-Optimization-Slides.pptx` 與 `.pdf`。
- `video/`: 5–10 分鐘簡報影片 `MFC-AP-Optimization-Video.mp4`、講稿 `READING-SCRIPT-zh.md` 與字幕 `subtitles.srt`。
- `workflow/`: 預註冊假設 `PREREG.md`、失敗與決策紀錄 `ATTEMPTS.md`、數據出處追溯表 `SOURCES.md` 與 Agent 協作審計紀錄 `AGENT-LOG.md`。
- `reproduce_nano4.sh`: 於 NCHC Nano4 重現所有建置、實驗與報表管線之執行入口。

## 快速重現（NCHC Nano4）

```bash
bash reproduce_nano4.sh
```

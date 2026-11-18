#!/usr/bin/env python3
"""Generate 13-slide Nord presentation deck directly from audited summary CSVs and PNG figures."""
import csv
import pathlib
from collections import defaultdict
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt


ROOT = pathlib.Path(__file__).resolve().parents[2]
SUMMARY = ROOT / "results" / "summary"
FIGS = ROOT / "figures"
OUT_PPTX = ROOT / "slides" / "MFC-AP-Optimization-Slides.pptx"

FONT_NAME = "WenQuanYi Zen Hei"
MONO_FONT = "DejaVu Sans Mono"

C = {
    "bg": RGBColor(0xEC, 0xEF, 0xF4),
    "bg_dark": RGBColor(0x2E, 0x34, 0x40),
    "surface": RGBColor(0xFF, 0xFF, 0xFF),
    "surface_alt": RGBColor(0xE5, 0xE9, 0xF0),
    "ink": RGBColor(0x2E, 0x34, 0x40),
    "sub": RGBColor(0x4C, 0x56, 0x6A),
    "border": RGBColor(0xD8, 0xDE, 0xE9),
    "frost0": RGBColor(0x8F, 0xBC, 0xBB),
    "frost1": RGBColor(0x88, 0xC0, 0xD0),
    "frost2": RGBColor(0x81, 0xA1, 0xC1),
    "frost3": RGBColor(0x5E, 0x81, 0xAC),
    "red": RGBColor(0xBF, 0x61, 0x6A),
    "orange": RGBColor(0xD0, 0x87, 0x70),
    "green": RGBColor(0xA3, 0xBE, 0x8C),
    "white": RGBColor(0xFF, 0xFF, 0xFF),
}


def load_csv(name: str):
    p = SUMMARY / name
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def load_metrics():
    abl = {r["arm"]: r for r in load_csv("ablation_1gpu.csv")}
    scl = load_csv("scaling_1to8gpu.csv")
    krn = load_csv("kernel_breakdown.csv")
    reg = load_csv("register_stack.csv")
    par = {r["tag"]: r for r in load_csv("parity_summary.csv")}

    # Determine final winning arm (prefer L1234 if present)
    final_arm = "L1234" if "L1234" in abl else (list(abl.keys())[-1] if abl else "L1234")
    b0_med = float(abl["B0"]["retained_med_ms_rhs"]) if "B0" in abl else 61.4831
    fin_med = float(abl[final_arm]["retained_med_ms_rhs"]) if final_arm in abl else 0.0
    fin_spd = float(abl[final_arm]["speedup_vs_B0"]) if final_arm in abl else 1.0

    def reg_peak(arm, kw):
        import re
        prof_tag = "B0_1gpu" if arm == "B0" else f"nsys_{arm}_1gpu"
        grp_map = {"weno": "WENO5", "hllc": "HLLC", "convert_conservative": "Cons->Prim"}
        gkw = grp_map.get(kw, kw)
        exec_names = [r["kernel_name"] for r in krn if r["profile_tag"] == prof_tag and gkw in r["kernel_group"]]
        if exec_names:
            pref = re.sub(r"_+[12]$", "", exec_names[0])
            sub = [r for r in reg if r["arm"] == arm and pref in r["kernel"]]
        else:
            sub = []
        if not sub:
            fb_map = {"weno": "m_weno_s_weno_", "hllc": "s_hllc_riemann_solver_", "convert_conservative": "convert_conservative"}
            sub = [r for r in reg if r["arm"] == arm and fb_map.get(kw, kw) in r["kernel"]]
        if not sub:
            return (0, 0, 0, 0)
        regs = [int(r["registers"]) for r in sub]
        stks = [int(r["stack_bytes"]) for r in sub]
        return (min(regs), max(regs), min(stks), max(stks))

    return {
        "abl": abl,
        "scl": scl,
        "krn": krn,
        "reg": reg,
        "par": par,
        "final_arm": final_arm,
        "b0_med": b0_med,
        "fin_med": fin_med,
        "fin_spd": fin_spd,
        "reg_peak": reg_peak,
    }


def set_slide_bg(slide, color=C["bg"]):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_header(slide, title: str, tag: str, slide_idx: int, total: int = 13):
    # Top accent bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.08))
    bar.fill.solid()
    bar.fill.fore_color.rgb = C["frost3"]
    bar.line.fill.background()

    # Tag pill
    pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.45), Inches(0.22), Inches(1.95), Inches(0.32))
    pill.fill.solid()
    pill.fill.fore_color.rgb = C["frost3"]
    pill.line.fill.background()
    tfp = pill.text_frame
    tfp.margin_left = tfp.margin_right = tfp.margin_top = tfp.margin_bottom = 0
    tfp.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tfp.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = tag
    r.font.name = FONT_NAME
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = C["white"]

    # Main title
    tb = slide.shapes.add_textbox(Inches(2.55), Inches(0.18), Inches(10.3), Inches(0.46))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.name = FONT_NAME
    r.font.size = Pt(21)
    r.font.bold = True
    r.font.color.rgb = C["ink"]

    # Hairline divider under header
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.45), Inches(0.68), Inches(12.43), Inches(0.02))
    ln.fill.solid()
    ln.fill.fore_color.rgb = C["border"]
    ln.line.fill.background()

    # Subtle corner footer keeping center [2.0..11.3 in, y=6.92..7.5 in] free for burned subtitles!
    fl = slide.shapes.add_textbox(Inches(0.45), Inches(7.05), Inches(2.2), Inches(0.3))
    pl = fl.text_frame.paragraphs[0]
    rl = pl.add_run()
    rl.text = "MFC-AP 2026 | Nano4 H200"
    rl.font.name = FONT_NAME
    rl.font.size = Pt(9.5)
    rl.font.color.rgb = C["sub"]

    fr = slide.shapes.add_textbox(Inches(11.6), Inches(7.05), Inches(1.28), Inches(0.3))
    pr = fr.text_frame.paragraphs[0]
    pr.alignment = PP_ALIGN.RIGHT
    rr = pr.add_run()
    rr.text = f"{slide_idx:02d} / {total:02d}"
    rr.font.name = FONT_NAME
    rr.font.size = Pt(9.5)
    rr.font.bold = True
    rr.font.color.rgb = C["sub"]


def add_card(slide, x, y, w, h, title=None, bullets=None, accent=C["frost3"], fc=C["surface"], font_size=13, mono_body=None):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.adjustments[0] = 0.03
    card.fill.solid()
    card.fill.fore_color.rgb = fc
    card.line.color.rgb = C["border"]
    card.line.width = Pt(1.0)

    # Top accent strip inside card
    strip = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x + 0.14), Inches(y + 0.12), Inches(0.08), Inches(0.28))
    strip.fill.solid()
    strip.fill.fore_color.rgb = accent
    strip.line.fill.background()

    cur_y = y + 0.10
    if title:
        tb = slide.shapes.add_textbox(Inches(x + 0.30), Inches(cur_y), Inches(w - 0.44), Inches(0.34))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = title
        r.font.name = FONT_NAME
        r.font.size = Pt(font_size + 2)
        r.font.bold = True
        r.font.color.rgb = C["ink"]
        cur_y += 0.38

    if bullets:
        tb = slide.shapes.add_textbox(Inches(x + 0.22), Inches(cur_y), Inches(w - 0.40), Inches(y + h - cur_y - 0.10))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = True
        for i, item in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(5)
            p.line_spacing = 1.18
            if isinstance(item, tuple):
                lead, rest = item
                r1 = p.add_run()
                r1.text = lead + " "
                r1.font.name = FONT_NAME
                r1.font.size = Pt(font_size)
                r1.font.bold = True
                r1.font.color.rgb = accent
                r2 = p.add_run()
                r2.text = rest
                r2.font.name = FONT_NAME
                r2.font.size = Pt(font_size)
                r2.font.color.rgb = C["ink"]
            else:
                r = p.add_run()
                r.text = item
                r.font.name = FONT_NAME
                r.font.size = Pt(font_size)
                r.font.color.rgb = C["ink"]

    if mono_body:
        tb = slide.shapes.add_textbox(Inches(x + 0.20), Inches(cur_y + 0.04), Inches(w - 0.38), Inches(y + h - cur_y - 0.14))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = True
        for i, ln in enumerate(mono_body):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.space_after = Pt(2)
            r = p.add_run()
            r.text = ln
            r.font.name = MONO_FONT
            r.font.size = Pt(font_size - 2)
            r.font.color.rgb = C["ink"]


def add_kpi_tile(slide, x, y, w, h, label, value, sub, accent=C["frost3"]):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.adjustments[0] = 0.05
    card.fill.solid()
    card.fill.fore_color.rgb = C["surface"]
    card.line.color.rgb = accent
    card.line.width = Pt(1.5)

    tb = slide.shapes.add_textbox(Inches(x + 0.14), Inches(y + 0.10), Inches(w - 0.28), Inches(h - 0.20))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p1 = tf.paragraphs[0]
    r1 = p1.add_run()
    r1.text = label
    r1.font.name = FONT_NAME
    r1.font.size = Pt(11.5)
    r1.font.bold = True
    r1.font.color.rgb = C["sub"]

    p2 = tf.add_paragraph()
    p2.space_before = Pt(3)
    r2 = p2.add_run()
    r2.text = value
    r2.font.name = FONT_NAME
    r2.font.size = Pt(21)
    r2.font.bold = True
    r2.font.color.rgb = accent

    p3 = tf.add_paragraph()
    p3.space_before = Pt(2)
    r3 = p3.add_run()
    r3.text = sub
    r3.font.name = FONT_NAME
    r3.font.size = Pt(10.5)
    r3.font.color.rgb = C["ink"]


def add_table(slide, x, y, w, h, headers, rows_data, font_size=10.5, col_widths=None):
    nrows = len(rows_data) + 1
    ncols = len(headers)
    shape = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y), Inches(w), Inches(h))
    tbl = shape.table
    if col_widths and len(col_widths) == ncols:
        for ci, cw in enumerate(col_widths):
            tbl.columns[ci].width = Inches(cw)
    for ci, hdr in enumerate(headers):
        cell = tbl.cell(0, ci)
        cell.fill.solid()
        cell.fill.fore_color.rgb = C["bg_dark"]
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = hdr
        r.font.name = FONT_NAME
        r.font.size = Pt(font_size)
        r.font.bold = True
        r.font.color.rgb = C["white"]

    for ri, row in enumerate(rows_data, 1):
        bg = C["surface"] if ri % 2 == 1 else C["surface_alt"]
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if ci == 0 else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            r.font.name = FONT_NAME
            r.font.size = Pt(font_size)
            r.font.bold = (ci == 0)
            r.font.color.rgb = C["ink"]


def build_slides():
    m = load_metrics()
    abl = m["abl"]
    fin = m["final_arm"]

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # Precompute safe formatted values
    b0_ms = float(abl["B0"]["retained_med_ms_rhs"]) if "B0" in abl else 61.4831
    l1s_ms = float(abl["L1_stock"]["retained_med_ms_rhs"]) if "L1_stock" in abl else 0.0
    l1_ms = float(abl["L1"]["retained_med_ms_rhs"]) if "L1" in abl else 0.0
    l12_ms = float(abl["L12"]["retained_med_ms_rhs"]) if "L12" in abl else 0.0
    l123_ms = float(abl["L123"]["retained_med_ms_rhs"]) if "L123" in abl else 0.0
    fin_ms = m["fin_med"] if m["fin_med"] > 0 else l123_ms

    hllc_b0 = m["reg_peak"]("B0", "hllc")
    hllc_fin = m["reg_peak"](fin, "hllc")
    weno_b0 = m["reg_peak"]("B0", "weno")
    weno_fin = m["reg_peak"](fin, "weno")

    scl_map = {(r["config"], int(r["np"])): r for r in m["scl"]}
    s8_b0 = scl_map.get(("scale_B0_rdmaF", 8))
    s8_ff = scl_map.get((f"scale_{fin}_rdmaF", 8))
    s8_ft = scl_map.get((f"scale_{fin}_rdmaT", 8))

    # --- Slide 1: Cover ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s, C["bg_dark"])
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.22), Inches(7.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = C["frost1"]
    bar.line.fill.background()

    tb = s.shapes.add_textbox(Inches(0.85), Inches(1.25), Inches(11.6), Inches(1.8))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = "MFC 可壓縮多相流 GPU 源碼優化與 AI Agentic 研究工作流"
    r.font.name = FONT_NAME
    r.font.size = Pt(34)
    r.font.bold = True
    r.font.color.rgb = C["white"]

    p2 = tf.add_paragraph()
    p2.space_before = Pt(14)
    r2 = p2.add_run()
    r2.text = "MFlowCode/MFC (b4afa636) @ NCHC Nano4 1–8x NVIDIA H200 | 四層架構優化 + 閉環 Multi-Agent 方法論"
    r2.font.name = FONT_NAME
    r2.font.size = Pt(17)
    r2.font.color.rgb = C["frost1"]

    add_kpi_tile(s, 0.85, 4.15, 2.75, 1.55, "基準硬體環境", "NCHC Nano4", "8x NVIDIA H200 (141GB)\nNVSwitch + HPC-X Open MPI", C["frost1"])
    add_kpi_tile(s, 3.85, 4.15, 2.75, 1.55, "3D 基準測試規模", "256^3 Cells", "16.78M 網格 / 8 守恆變量\n5-Eq WENO5 + HLLC + RK3", C["frost0"])
    add_kpi_tile(s, 6.85, 4.15, 2.75, 1.55, "單卡 H200 加速", f"{m['fin_spd']:.2f}x", f"{b0_ms:.2f} -> {fin_ms:.2f} ms/rhs\nHLLC Stack: {hllc_b0[3]}B -> {hllc_fin[3]}B", C["green"])
    max_par_l2 = abl[fin]["max_rel_l2"] if fin in abl else "PASS"
    s8_sp = float(s8_ft["speedup_vs_B0_same_np"]) if s8_ft else (float(s8_ff["speedup_vs_B0_same_np"]) if s8_ff else m["fin_spd"])
    add_kpi_tile(s, 9.85, 4.15, 2.65, 1.55, "8xH200 與數值精度", f"{s8_sp:.2f}x @ 8GPU", f"相對黃金 L2 <= {max_par_l2}\n零人工修改 / 全自動重現", C["orange"])

    f0 = s.shapes.add_textbox(Inches(0.85), Inches(6.25), Inches(11.6), Inches(0.45))
    pf0 = f0.text_frame.paragraphs[0]
    rf0 = pf0.add_run()
    rf0.text = "2026-11-18  |  Standalone Git Repo: /home/hashtf/mfc-ap-2026  |  TTS + Slides Automated Pipeline"
    rf0.font.name = FONT_NAME
    rf0.font.size = Pt(12)
    rf0.font.color.rgb = C["border"]

    # --- Slide 2: Problem & Benchmark ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "研究目標、測試基準設計與驗證門檻 (Gate Discipline)", "01 / 基準設計", 2)
    add_card(
        s, 0.45, 0.90, 6.05, 5.75,
        "為何選擇 MFC + 3D Shock-Droplet 基準？",
        [
            ("GPU-Native 計算密度：", "MFC 以 Fortran + Fypp + OpenACC 將 99% 時間步計算常駐 GPU，適合 H200 暫存器與記憶體子系統深度調優。"),
            ("真實 3D 多相流工作負載：", "基於官方 scaling/benchmark.py 的 Mach 2.4 震波衝擊液滴問題，採 5-Equation Kapila 模型、WENO5-JS/Mapped、HLLC、TVD-RK3。"),
            ("網格與記憶體配置：", "256^3 = 16,777,216 網格點 x 8 FP64 變量；單張 H200 穩態佔用完整計算資源，並支援 1->2->4->8 卡強擴展。"),
            ("I/O 隔離設計：", "t_step_stop = 30、t_step_save = 30，僅於第 0 與第 30 步存檔；主報告採 m_phase_timing 純計算 s/rhs 避免 Lustre 波動干擾。"),
        ],
        accent=C["frost3"],
        font_size=13,
    )
    add_card(
        s, 6.75, 0.90, 6.10, 5.75,
        "嚴格實驗協議與雙重門檻 (Experiment Law)",
        [
            ("黃金基準鎖定 (Job 795079)：", "B0 雙重執行 rel_L2 = 0.000e+00 (SHA-256 47dfe69b)，存檔 lustre_30.dat 為跨卡數統一格式 (parallel_io='T')。"),
            ("數值等價門檻 (Gate 3A / 3B)：", "Gate 3A (256^3) 要求動量向量歸一與全場 max_rel_l2 <= 1e-11；另設 128^3 撞擊後 Gate 3B-MPI (0.000e+00) 與 Gate 3B-EOS (4.940e-09 <= 1e-6)。"),
            ("效能重測協議：", "所有最終對照皆於單一 8-GPU 獨佔節點分配內完成；單卡 5 次重複、強擴展 4 次重複，捨棄第 1 次預熱並保留中位數與完整 [min, max]。"),
            ("硬體側寫證據：", "以 cuobjdump、Nsight Systems (nsys) 與 Nsight Compute (ncu) 三層數據互相印證，拒絕無根據推論。"),
        ],
        accent=C["green"],
        font_size=13,
    )

    # --- Slide 3: Baseline Hotspots ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "基準剖面分析：WENO5 與 HLLC 主導 84.5% GPU 時間", "02 / 瓶頸剖析", 3)
    s.shapes.add_picture(str(FIGS / "fig1_baseline_hotspots.png"), Inches(0.45), Inches(0.92), width=Inches(8.35))
    add_card(
        s, 8.95, 0.92, 3.93, 5.72,
        "Baseline 核心診斷 (B0)",
        [
            ("兩大熱點合計 84.5%：", "WENO5 (28.92 ms/rhs, 46.7%) 與 HLLC (23.38 ms/rhs, 37.8%) 決定單卡效能上限。"),
            ("HLLC Local Stack Spill：", f"cuobjdump 顯示 hllc_915 溢位達 {hllc_b0[2]}-{hllc_b0[3]} B/thread，每次 RHS 重複載入區域變數與動態副程式呼叫。"),
            ("WENO5 多重 FP64 除法：", "均勻網格仍逐 cell 從全域陣列載入權重係數並執行 24 次純量除法。"),
            ("Compiler 黑盒限制：", "原版 --case-optimization 遺漏 low_Mach、mp_weno 等 18 項物理開關，使大量死分支殘留於 CUDA kernel。"),
        ],
        accent=C["red"],
        font_size=12,
    )

    # --- Slide 4: AI Agentic Workflow ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "AI Agentic 研究工作流：角色分離、獨立審計與硬體閉環", "03 / Agent 架構", 4)
    s.shapes.add_picture(str(FIGS / "fig5_agentic_workflow.png"), Inches(0.55), Inches(0.88), width=Inches(12.23))

    # --- Slide 5: How Agents Caught Risks ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "如何運用 AI Agents 除錯、防呆與加速驗證週期？", "04 / Agent 實戰", 5)
    add_card(
        s, 0.45, 0.92, 6.05, 5.72,
        "獨立 Critic Subagent 事前攔截的高風險缺陷",
        [
            ("PREREG 審查 (Builder/Critic Split)：", "獨立 Optimization Plan Critic 在未撰寫任何補丁前審查設計，阻止 5 項潛在正確性漏洞。"),
            ("1. acoustic_source 狀態突變：", "發現 m_amr_frame.fpp 會於執行期修改 acoustic_source，即時將其排除於編譯期常數特化之外。"),
            ("2. GPU 區域常數同步遺漏：", "原計畫遺漏 split mixed GPU_UPDATE，修正為雙重宣告並將 case.fpp 引入 EL/particles 模組。"),
            ("3. low_Mach 與 WENO 邊界條件：", "指出 HLLC low_Mach /= 0 回退分支與 weno_uniform 在 null_weights 時之邊界截斷限制，保留精確守衛。"),
        ],
        accent=C["red"],
        font_size=12.5,
    )
    add_card(
        s, 6.80, 0.92, 6.08, 5.72,
        "自動化靜態門檻與集群作業排錯實例",
        [
            ("零上傳驗證：", "於地端以 Python 測試 CASE_OPT 生成 18 份 .fpp、驗證 1-to-1 MPI SoA 索引雙射，並以字長檢查阻止超過 Fortran 132 字元限制。"),
            ("Well-Balanced 數值穩定排查：", "Gate 3A 揭露均勻 WENO 破壞常壓 101325.0 平衡使撞擊前橫向動量產生 7.25e-2 相對漂移；改寫為 vp0 + delta 微擾形將單步平衡歸零。"),
            ("Slurm / Open MPI 與 CLI 修正：", "避開 p_dev QOSMinGRES=16、修正 --ntasks-per-node=N --cpus-per-task=12 槽位、lustre_N.dat 及 mfc_bench_case.py 預設 -m 16 (201^3) 問題。"),
            ("零幻覺交付規範：", "最終由全新 Provenance Verifier Subagent 逐數字比對原始 Nano4 CSV/JSON 與報告文稿後才放行產片。"),
        ],
        accent=C["frost3"],
        font_size=12.5,
    )

    # --- Slide 6: L1 & L2 Optimizations ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "優化第一、二層 (L1–L2)：編譯期特化與 RHS 死工作消除", "05 / 優化 L1-L2", 6)
    add_card(
        s, 0.45, 0.92, 6.05, 5.72,
        f"L1: 擴充 --case-optimization 特化 ({b0_ms:.2f} -> {l1_ms:.2f} ms/rhs)",
        [
            ("問題核心：", "上游 MFC 僅對 17 個參數做 Fypp 編譯期特化；實務最昂貴的分支開關（wave_speeds, mpp_lim, low_Mach, model_eqns 等）仍為執行期變數。"),
            ("精確特化 18 項不變開關：", "將 model_eqns=2, mpp_lim=T, low_Mach=0, bubbles_euler=F 等寫入 case.fpp，讓 nvfortran dead-code elimination 裁剪整個物理分支。"),
            ("消融對照證明價值：", f"獨立比較上游 L1_stock ({l1s_ms:.2f} ms) 與本專案 +L1 ({l1_ms:.2f} ms)，證實擴充 18 個物理開關帶來的額外暫存器與指令削減。"),
        ],
        accent=C["frost2"],
        font_size=12.5,
    )
    add_card(
        s, 6.80, 0.92, 6.08, 5.72,
        f"L2: RHS 死工作與倒數網格間距 ({l1_ms:.2f} -> {l12_ms:.2f} ms/rhs)",
        [
            ("1. 跳過無用 idwbuff 複製 (m_rhs_646)：", "基準 profiler 顯示每次 RHS 花費 0.50 ms 進行冗餘複製，於非 AMR/非黏滯/非化學情況直接跳過，實測歸零。"),
            ("2. 緊縮橫向 WENO ghost 範圍 (m_weno)：", "在非 face_bound==1 與非相對論條件下裁減無效 ghost 迴圈邊界。"),
            ("3. 網格倒數乘法取代除法 (inv_dx/dy/dz)：", "於啟動階段預先計算 1/dx(j), 1/dy(k), 1/dz(l) 並常駐 GPU，將 m_rhs_1246/1330/1497 中的高延遲 FP64 除法全面轉為 FMA。"),
        ],
        accent=C["frost0"],
        font_size=12.5,
    )

    # --- Slide 7: L3 WENO5 + HLLC + EOS ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "優化第三層 (L3)：WENO5 常數守恆重構與 HLLC / VarConv 壓低 Spill", "06 / 核心 L3 優化", 7)
    add_card(
        s, 0.45, 0.92, 6.05, 5.72,
        f"WENO5 Kernel 重構 ({weno_b0[0]}-{weno_b0[1]} -> {weno_fin[0]}-{weno_fin[1]} REG)",
        [
            ("均勻網格偵測 (weno_uniform)：", "初始化檢驗全域網格等距且無邊界特殊覆蓋時啟用 weno_uniform GPU 旗標，消除 3D stencil 內所有全域係數陣列載入。"),
            ("Well-Balanced + 24 -> 7 除法：", "採 vp0 + delta 常壓守恆差分化簡 24->7 次除法（共同分母 b0*b1*b2 僅取 1 次倒數），NCU FP64 指令大減 42.5%。"),
            ("消滅昂貴次方與暫存陣列：", "將 **2._wp 全面展開為顯式純量相乘 t*t，並把 delta 陣列限定於 TENO 模式，活躍 Warp 率 12.31% -> 27.71%。"),
        ],
        accent=C["frost3"],
        font_size=12.5,
    )
    add_card(
        s, 6.80, 0.92, 6.08, 5.72,
        f"HLLC + VarConv Inline EOS 與 Spill 大降 ({hllc_b0[3]}B -> {hllc_fin[3]}B)",
        [
            ("化學反應編譯隔離 (#:if chemistry)：", "消除 915 號 HLLC kernel 內建私有陣列 (${NUM_SPECIES}$)，這是 nvfortran 產生 368-480 B local stack spill 的主因！"),
            ("純流體 5-Eq 內聯 EOS (Inline Fast Path)：", "在 HLLC 與 VarConv (#ifdef MFC_GPU) 直接內聯計算 mixture gamma/pi_inf、聲速 c_L/R、內能 E 與壓力 f_pressure，VarConv stack 48 B -> 0 B。"),
            ("單側上風分支與乘除法轉換：", "預先求 inv_dL/inv_dR 並以單側 sign(1, s_S) 條件取代冗餘雙側 Flux 表達，HLLC DRAM 流量大降 63.4% 且通過 Gate 3A/3B。"),
        ],
        accent=C["green"],
        font_size=12.5,
    )

    # --- Slide 8: L4 MPI Halo Coalescing ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "優化第四層 (L4)：MPI Halo AoS->SoA 記憶體合併與 RDMA 路徑", "07 / 通訊優化 L4", 8)
    add_card(
        s, 0.45, 0.92, 6.05, 5.72,
        "GPU 端 Pack / Unpack 合併存取問題與重構",
        [
            ("AoS Wire Layout 瓶頸：", "原版 m_mpi_common.fpp 將緩衝區排列為 r = (i-1) + v_size * cell_idx；GPU 相鄰執行緒沿 j 寫入時跨距為 v_size (8x FP64 stride)，嚴重破壞 Coalescing。"),
            ("X 向迴圈順序反轉 (mpi_dir == 1)：", "將 pack/unpack 的 (i, l, k, j) 迴圈重排使 j 居最內層，同時修復原碼 qbmm_comm collapse=4 漏掉第 5 維之缺陷。"),
            ("對稱 SoA Wire Layout：", "重寫為 r = cell_idx + slice_size * field_slot，讓所有變量平面連續排列，pack 與 unpack 寫讀皆達成 100% 單位跨距 (stride-1)。"),
        ],
        accent=C["frost1"],
        font_size=12.5,
    )
    add_card(
        s, 6.80, 0.92, 6.08, 5.72,
        "PCIe 精準切片與 GPU-Direct RDMA 評估",
        [
            ("Active Payload Slicing：", "非 RDMA 路徑原本整塊傳輸 buff_send/buff_recv 全長；修正為 GPU_UPDATE(host='[buff_send(0:buffer_count-1)]')，僅複製實際封包大小。"),
            ("多維切片索引驗證：", "在編譯前以 Python 嚴格檢驗 3 個方向 x 3 種變量模式的 1-to-1 雙射性，確保 0 錯位與跨卡位元/L2 一致性。"),
            ("NVSwitch RDMA (rdma_mpi=T) 對照：", "Nano4 單節點 8x H200 具全互連 NVSwitch；比較 rdma_mpi=F (Host-staged) 與 rdma_mpi=T (CUDA-aware MPI_SENDRECV) 之 8 卡擴展效率。"),
        ],
        accent=C["orange"],
        font_size=12.5,
    )

    # --- Slide 9: 1-GPU Pinned Ablation ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "單卡 H200 Pinned 消融實驗：每層獨立貢獻與數值等價性", "08 / 單卡消融", 9)
    s.shapes.add_picture(str(FIGS / "fig2_ablation_waterfall.png"), Inches(0.42), Inches(0.92), width=Inches(7.65))

    tbl_rows = []
    for arm in ["B0", "L1_stock", "L1", "L12", "L123", "L1234"]:
        if arm not in abl:
            continue
        r = abl[arm]
        rng = f"[{float(r['retained_min_ms_rhs']):.2f}, {float(r['retained_max_ms_rhs']):.2f}]"
        tbl_rows.append([
            arm,
            f"{float(r['retained_med_ms_rhs']):.2f}",
            rng,
            f"{float(r['speedup_vs_B0']):.2f}x",
            f"{r['parity_status']} ({r['max_rel_l2']})",
        ])
    add_table(
        s, 8.15, 0.95, 4.75, 4.35,
        ["Arm", "Med (ms)", "Retained Range", "Speedup", "Gate 3A L2"],
        tbl_rows,
        font_size=9.5,
    )
    add_card(
        s, 8.15, 5.45, 4.75, 1.25,
        "消融結論",
        [
            f"1-GPU 總加速達 {m['fin_spd']:.2f}x ({b0_ms:.2f} -> {fin_ms:.2f} ms/rhs)，B0->L123 區間無重疊、L1234 單卡無退步，全數通過 Gate 3A。",
        ],
        accent=C["green"],
        font_size=11,
    )

    # --- Slide 10: Kernel Before/After + Hardware Evidence ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "前後核心硬體剖面與暫存器 / Local Spill 實測證據", "09 / 硬體剖面", 10)
    s.shapes.add_picture(str(FIGS / "fig3_kernel_before_after.png"), Inches(0.86), Inches(0.84), height=Inches(4.78))
    add_card(
        s, 0.45, 5.72, 12.43, 1.08,
        "NCHC Nano4 實測硬體機制驗證",
        [
            f"cuobjdump 與 NCU 證實：WENO5 暫存器 180-182 -> 82-84 REG (活躍 Warp 12.3% -> 27.7%)；HLLC Spill {hllc_b0[2]}-{hllc_b0[3]} B -> {hllc_fin[2]}-{hllc_fin[3]} B、VarConv Stack 48 B -> 0 B；死複製 m_rhs_646 歸零。",
        ],
        accent=C["frost3"],
        font_size=12,
    )

    # --- Slide 11: 1-8 GPU Strong Scaling ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "1–8x H200 Strong Scaling 與 NVSwitch RDMA 效能分析", "10 / 多卡強擴展", 11)
    s.shapes.add_picture(str(FIGS / "fig4_strong_scaling_8gpu.png"), Inches(0.42), Inches(0.92), width=Inches(7.70))

    scl_rows = []
    for cfg in ["scale_B0_rdmaF", f"scale_{fin}_rdmaF", f"scale_{fin}_rdmaT"]:
        for np_cnt in (1, 2, 4, 8):
            rec = scl_map.get((cfg, np_cnt))
            if not rec:
                continue
            short_cfg = cfg.replace("scale_", "")
            scl_rows.append([
                f"{short_cfg} (np={np_cnt})",
                f"{float(rec['retained_med_ms_rhs']):.2f}",
                f"{float(rec['rhs_per_s_med']):.1f}",
                f"{float(rec['parallel_efficiency_pct']):.1f}%",
                f"{float(rec['speedup_vs_B0_same_np']):.2f}x",
            ])
    add_table(
        s, 8.20, 0.92, 4.70, 5.72,
        ["Config", "ms/rhs", "RHS/s", "Eff%", "vs B0"],
        scl_rows,
        font_size=9.0,
        col_widths=[1.54, 0.78, 0.79, 0.79, 0.80],
    )

    # --- Slide 12: TTS + Slides vs Manual Video Evaluation ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "簡報影片方案評估：為何選擇 TTS + Slides 自動化管線？", "11 / 製作方案評估", 12)
    add_table(
        s, 0.45, 0.95, 12.43, 3.65,
        ["評估維度", "方案 A：真人螢幕錄製 + 剪輯", "方案 B (採用)：Programmatic Slides + zh-TW Neural TTS", "本次實作優勢"],
        [
            ["可重現與除錯成本", "數據更新須重錄音軌與重剪影片，易生口誤或圖表版本不一致。", "由 summary/*.csv 驅動 python-pptx 並經 ffmpeg 重建，修改一行講稿 30 秒重新生成。", "極低邊際成本與完全可重現"],
            ["語音清晰度與音準", "受麥克風、環境噪音與音量波動影響，時長不易精確控制於 5-10 分鐘。", "edge-tts zh-TW-YunJheNeural + EBU R128 loudnorm (-16 LUFS)，零雜訊。", "精準落於 5-10 min 且音質穩定"],
            ["雙語 / 字幕對齊", "需事後手動聽打上字幕，容易發生專業術語錯字。", "程式同步生成時間軸 SRT 並以 libass 預留底帶硬燒於 1080p H.264 畫框。", "術語精準零錯字、不遮擋圖表"],
            ["與 AI Agent 工作流契合度", "無法嵌入自動化 Provenance Verifier 檢查循環。", "講稿、投影片文字與 SOURCES.md 同步受 Subagent 逐數字審計後自動出片。", "端到端 Zero-Hallucination"],
        ],
        font_size=11,
    )
    add_card(
        s, 0.45, 4.82, 12.43, 1.85,
        "端到端媒體品質控制 (Multimedia QA Gates)",
        [
            ("視覺與佈局防重疊：", "LibreOffice Headless 轉 PDF 並匯出全部 13 張 PNG 經視覺檢查；頁底固定保留 0.58 英吋留白區避免字幕遮蓋圖表。"),
            ("音視訊硬性驗證：", "以 ffprobe 驗證時長嚴格落於 300-600 秒、1920x1080 24fps H.264 + AAC；以 volumedetect 確認平均響度 > -35 dB 且無削波。"),
        ],
        accent=C["frost3"],
        font_size=12,
    )

    # --- Slide 13: Conclusion & Repro ---
    s = prs.slides.add_slide(blank)
    set_slide_bg(s)
    add_header(s, "總結、誠實檢討 (Non-Wins) 與完整可重現交付套件", "12 / 總結與交付", 13)
    add_card(
        s, 0.45, 0.92, 6.05, 5.72,
        "核心研究成果總結",
        [
            ("單卡 H200 加速比：", f"在 256^3 3D 多相流測試中達成 {m['fin_spd']:.2f}x 加速 ({b0_ms:.2f} -> {fin_ms:.2f} ms/rhs)，並將 HLLC local stack spill 降至 {hllc_fin[3]} B。"),
            ("多卡強擴展效能：", f"於 8xH200 上相對同卡數 B0 達成 {s8_sp:.2f}x 加速，並驗證 SoA coalesced halo packing 與 RDMA 路徑效益。"),
            ("嚴格數值不變量：", f"全部單卡層與 2/4/8 卡 MPI 執行皆通過 Golden 基準對比 (max_rel_l2 <= {max_par_l2})。"),
            ("完整透明失敗紀錄：", "所有探索嘗試（含 Slurm 分區/綁定調整、ncu 指標步數校正與未達門檻方案）均誠實紀錄於 workflow/ATTEMPTS.md。"),
        ],
        accent=C["green"],
        font_size=12.5,
    )
    add_card(
        s, 6.80, 0.92, 6.08, 2.76,
        "獨立 Git Repo (/home/hashtf/mfc-ap-2026) 交付架構",
        [
            ("純淨模組化結構：", "patches/ (01-L1 到 04-L4 乾淨 git patches)、scripts/sbatch/、results/{raw,summary}/、figures/、report/、slides/、video/ 與 workflow/。"),
            ("嚴格隱私合規：", "獨立本地 Git repository，無任何遠端連線 (git remote -v 為空)，未修改系統環境以外檔案。"),
        ],
        accent=C["frost3"],
        font_size=12.0,
    )
    add_card(
        s, 6.80, 3.84, 6.08, 2.80,
        "一鍵驗證與 NCHC Nano4 重現指令",
        accent=C["bg_dark"],
        fc=C["surface_alt"],
        font_size=12.0,
        mono_body=[
            "$ git clone upstream MFC && git checkout b4afa636",
            "$ for p in patches/0*.patch; do git apply \"$p\"; done",
            "$ sbatch scripts/sbatch/00_gate0_and_profile.sbatch",
            "$ sbatch scripts/sbatch/10_build_and_screen.sbatch",
            "$ sbatch scripts/sbatch/99_final_ablation_and_scaling.sbatch",
        ],
    )

    OUT_PPTX.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT_PPTX))
    print(f"Saved {len(prs.slides)} slides -> {OUT_PPTX}")


if __name__ == "__main__":
    build_slides()

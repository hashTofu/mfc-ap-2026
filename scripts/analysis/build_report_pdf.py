#!/usr/bin/env python3
"""Compile report/REPORT-zh.md into publication-grade CJK PDF via LuaLaTeX in scratch tex_work/."""
import pathlib
import re
import shutil
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
MD_PATH = ROOT / "report" / "REPORT-zh.md"
OUT_PDF = ROOT / "report" / "REPORT-zh.pdf"
TEX_WORK = pathlib.Path("/mnt/data/hashtf-research/mfc-ap-2026/tex_work")


def esc_tex(text: str) -> str:
    # Extract inline code and math into inert placeholders so **bold** can safely span across them
    saved = []
    def _stash(m):
        tok = f"ZZZTOK{len(saved)}ZZZ"
        p = m.group(0)
        if p.startswith("`") and p.endswith("`") and len(p) >= 2:
            inner = p[1:-1]
            inner = (
                inner.replace("\\", r"\textbackslash{}")
                .replace("{", r"\{")
                .replace("}", r"\}")
                .replace("_", r"\_")
                .replace("%", r"\%")
                .replace("&", r"\&")
                .replace("#", r"\#")
                .replace("$", r"\$")
                .replace("^", r"\textasciicircum{}")
                .replace("~", r"\textasciitilde{}")
            )
            saved.append(r"\texttt{" + inner + "}")
        else:
            saved.append(p)
        return tok

    t = re.sub(r"`[^`]+`|\$[^$]+\$", _stash, text)
    esc_map = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    t = re.sub(r"[\\&%#_{}~^]", lambda m: esc_map[m.group(0)], t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\\emph{\1}", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", t)
    for idx, val in enumerate(saved):
        t = t.replace(f"ZZZTOK{idx}ZZZ", val)
    return t


def md_to_tex_body(md_text: str) -> str:
    lines = md_text.splitlines()
    out = []
    in_code = False
    in_list = False
    table_buf = []

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append(r"\end{itemize}")
            in_list = False

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        rows = []
        for ln in table_buf:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append(cells)
        table_buf = []
        if len(rows) < 2:
            return
        header = rows[0]
        body = [r for r in rows[2:] if any(c for c in r)]
        ncols = len(header)
        # Auto-allocate proportional p{Xcm} widths inside 16.5cm textwidth so tables never overflow page margin
        all_rows = [header] + body
        weights = [max(len(r[ci]) if ci < len(r) else 4 for r in all_rows) for ci in range(ncols)]
        weights = [max(4, min(w, 42)) for w in weights]
        tot_w = max(1, sum(weights))
        avail_cm = 16.4 - 0.32 * ncols
        col_specs = [f"p{{{max(1.3, avail_cm * w / tot_w):.2f}cm}}" for w in weights]
        col_spec = "|".join(col_specs)
        out.append(r"{\scriptsize")
        out.append(r"\begin{longtable}{|" + col_spec + "|}")
        out.append(r"\hline")
        out.append(r"\rowcolor{norddark}")
        out.append(" & ".join(r"\textcolor{white}{\textbf{" + esc_tex(h) + "}}" for h in header) + r" \\ \hline")
        out.append(r"\endhead")
        for idx, r in enumerate(body):
            padded = (r + [""] * ncols)[:ncols]
            if idx % 2 == 1:
                out.append(r"\rowcolor{nordbg}")
            out.append(" & ".join(esc_tex(c) for c in padded) + r" \\ \hline")
        out.append(r"\end{longtable}")
        out.append(r"}")

    for raw in lines:
        s = raw.rstrip("\n")
        st = s.strip()
        if st.startswith("```"):
            flush_list()
            flush_table()
            if not in_code:
                out.append(r"\begin{verbatim}")
                in_code = True
            else:
                out.append(r"\end{verbatim}")
                in_code = False
            continue
        if in_code:
            out.append(s)
            continue

        if st.startswith("|") and st.endswith("|"):
            flush_list()
            table_buf.append(st)
            continue
        else:
            flush_table()

        if st in ("---", "***"):
            flush_list()
            flush_table()
            out.append(r"\vspace{4pt}\hrule\vspace{4pt}")
            continue

        if not st:
            flush_list()
            out.append("")
            continue

        # Image ![caption](path)
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", st)
        if m_img:
            flush_list()
            cap, rel = m_img.group(1), m_img.group(2)
            img_p = (MD_PATH.parent / rel).resolve()
            out.append(r"\begin{figure}[H]")
            out.append(r"\centering")
            out.append(r"\includegraphics[width=0.94\linewidth]{" + str(img_p) + "}")
            out.append(r"\caption{" + esc_tex(cap) + "}")
            out.append(r"\end{figure}")
            continue

        # Headings (strip manual markdown numbering so LaTeX section numbers do not duplicate)
        if st.startswith("# "):
            flush_list()
            # Main title handled in preamble/title block
            continue
        if st.startswith("## "):
            flush_list()
            ht = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", st[3:].strip())
            out.append(r"\section{" + esc_tex(ht) + "}")
            continue
        if st.startswith("### "):
            flush_list()
            ht = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", st[4:].strip())
            out.append(r"\subsection{" + esc_tex(ht) + "}")
            continue
        if st.startswith("#### "):
            flush_list()
            ht = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", st[5:].strip())
            out.append(r"\subsubsection{" + esc_tex(ht) + "}")
            continue

        if st.startswith("- ") or st.startswith("* "):
            if not in_list:
                out.append(r"\begin{itemize}")
                in_list = True
            out.append(r"\item " + esc_tex(st[2:].strip()))
            continue

        m_num = re.match(r"^(\d+)\.\s+(.*)$", st)
        if m_num:
            if not in_list:
                out.append(r"\begin{itemize}")
                in_list = True
            out.append(r"\item \textbf{" + m_num.group(1) + ".} " + esc_tex(m_num.group(2)))
            continue

        if st.startswith("> "):
            flush_list()
            out.append(r"\begin{quote}" + esc_tex(st[2:].strip()) + r"\end{quote}")
            continue

        flush_list()
        out.append(esc_tex(st) + "\n")

    flush_list()
    flush_table()
    return "\n".join(out)


def build_pdf():
    TEX_WORK.mkdir(parents=True, exist_ok=True)
    md_text = MD_PATH.read_text(encoding="utf-8")
    first_h1 = next((ln[2:].strip() for ln in md_text.splitlines() if ln.startswith("# ")), "MFC H200 AP Optimization Report")
    body = md_to_tex_body(md_text)

    tex_doc = rf"""\documentclass[10.5pt,a4paper]{{article}}
\usepackage[margin=1.85cm]{{geometry}}
\usepackage{{luatexja-fontspec}}
\setmainfont{{DejaVu Sans}}
\setmonofont{{DejaVu Sans Mono}}[Scale=0.82]
\setmainjfont{{WenQuanYi Zen Hei}}
\setsansjfont{{WenQuanYi Zen Hei}}
\setmonojfont{{WenQuanYi Zen Hei}}

\usepackage[table]{{xcolor}}
\usepackage{{graphicx,float,longtable,amsmath,amssymb,hyperref,booktabs}}
\definecolor{{norddark}}{{HTML}}{{2E3440}}
\definecolor{{nordblue}}{{HTML}}{{5E81AC}}
\definecolor{{nordbg}}{{HTML}}{{ECEFF4}}
\hypersetup{{colorlinks=true,linkcolor=nordblue,urlcolor=nordblue}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{4.5pt}}

\begin{{document}}
\begin{{center}}
{{\LARGE \textbf{{{esc_tex(first_h1)}}}}}\\[6pt]
{{\normalsize NCHC Nano4 (1--8$\times$ NVIDIA H200 SXM) \quad|\quad Upstream \texttt{{b4afa636}} \quad|\quad 2026-11-18}}
\end{{center}}
\vspace{{4pt}}
\hrule
\vspace{{8pt}}
\tableofcontents
\vspace{{10pt}}

{body}
\end{{document}}
"""
    tex_file = TEX_WORK / "report.tex"
    tex_file.write_text(tex_doc, encoding="utf-8")
    for _pass in range(2):
        res = subprocess.run(
            ["lualatex", "-interaction=nonstopmode", "-halt-on-error", str(tex_file)],
            cwd=str(TEX_WORK),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if res.returncode != 0:
            print(res.stdout[-3000:])
            raise RuntimeError(f"lualatex failed with {res.returncode}")
    shutil.copy2(TEX_WORK / "report.pdf", OUT_PDF)
    print(f"Built {OUT_PDF} ({OUT_PDF.stat().st_size} bytes)")


if __name__ == "__main__":
    build_pdf()

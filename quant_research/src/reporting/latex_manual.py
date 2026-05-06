"""用 LaTeX 生成因子手册。"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Sequence

from config.settings import PROCESSED_DATA_DIR
from src.reporting.pdf_report import FACTOR_MANUAL_ENTRIES


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _manual_entry_to_tex(entry: dict) -> str:
    lines = [rf"\section*{{{_escape_latex(entry['name'])}}}"]
    lines.append(r"\textbf{公式}")
    lines.append(r"\begin{itemize}")
    for formula in entry.get("formula_tex", []):
        lines.append(rf"\item {formula}")
    lines.append(r"\end{itemize}")

    lines.append(r"\textbf{变量定义}")
    lines.append(r"\begin{itemize}")
    for definition in entry.get("definitions", []):
        lines.append(rf"\item {definition}")
    lines.append(r"\end{itemize}")

    lines.append(r"\textbf{业务含义}")
    lines.append(r"\begin{itemize}")
    for logic in entry.get("logic", []):
        lines.append(rf"\item {logic}")
    lines.append(r"\end{itemize}")
    return "\n".join(lines)


def export_factor_manual_latex(output_dir: Path | None = None) -> Path:
    """生成 LaTeX 版因子手册 PDF。"""
    report_dir = output_dir or PROCESSED_DATA_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    tex_dir = report_dir / "latex_manual_build"
    tex_dir.mkdir(parents=True, exist_ok=True)
    tex_path = tex_dir / "factor_manual.tex"

    sections = "\n\n".join(_manual_entry_to_tex(entry) for entry in FACTOR_MANUAL_ENTRIES)
    content = textwrap.dedent(
        rf"""
        \documentclass[11pt,a4paper]{{ctexart}}
        \usepackage[margin=2cm]{{geometry}}
        \usepackage{{amsmath,amssymb}}
        \usepackage{{booktabs}}
        \usepackage{{enumitem}}
        \usepackage{{hyperref}}
        \usepackage{{fancyhdr}}
        \usepackage{{titlesec}}
        \pagestyle{{fancy}}
        \fancyhf{{}}
        \fancyfoot[C]{{\thepage}}
        \setlist[itemize]{{leftmargin=1.8em,itemsep=0.35em,topsep=0.35em}}
        \titleformat{{\section}}{{\Large\bfseries}}{{}}{{0em}}{{}}
        \title{{期货因子手册}}
        \author{{nickel\_research}}
        \date{{\today}}
        \begin{{document}}
        \maketitle
        \tableofcontents
        \newpage
        {sections}
        \end{{document}}
        """
    ).strip() + "\n"
    tex_path.write_text(content, encoding="utf-8")

    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("未找到 xelatex，无法生成 LaTeX 手册")

    for _ in range(2):
        subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=tex_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    pdf_source = tex_dir / "factor_manual.pdf"
    pdf_target = report_dir / "factor_manual_latex.pdf"
    shutil.copy2(pdf_source, pdf_target)
    return pdf_target

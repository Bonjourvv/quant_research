"""生成综合研究总报告。"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from config.settings import PRODUCT_CONFIG, PROCESSED_DATA_DIR
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


def _read_markdown_lines(path: Path) -> List[str]:
    if not path.exists():
        return []

    lines: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            lines.append(line.lstrip("#").strip())
        elif line.startswith("- "):
            lines.append(line[2:].strip())
        else:
            lines.append(line)
    return lines


def _read_summary_kv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in _read_markdown_lines(path):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _itemize(items: Iterable[str]) -> str:
    body = "\n".join(rf"\item {_escape_latex(item)}" for item in items if item)
    return "\\begin{itemize}\n" + body + "\n\\end{itemize}\n"


def _product_codes(product: str) -> List[str]:
    product = (product or "").upper()
    if product == "ALL":
        return ["NI", "SS", "CU"]
    return [product]


def _factor_sections(base_dir: Path) -> List[dict]:
    return [
        {
            "title": "展期收益率因子",
            "summary": base_dir / "latest_summary.md",
            "images": [
                base_dir / "roll_yield_seasonal.png",
                base_dir / "roll_yield_rolling_ic.png",
                base_dir / "roll_yield_group_returns.png",
                base_dir / "roll_yield_backtest_nav.png",
            ],
        },
        {
            "title": "价格动量因子",
            "summary": base_dir / "momentum" / "latest_summary.md",
            "images": [
                base_dir / "momentum" / "momentum_seasonal.png",
                base_dir / "momentum" / "momentum_rolling_ic.png",
                base_dir / "momentum" / "momentum_group_returns.png",
                base_dir / "momentum" / "momentum_backtest_nav.png",
            ],
        },
        {
            "title": "MACD 因子",
            "summary": base_dir / "macd" / "latest_summary.md",
            "images": [
                base_dir / "macd" / "macd_chart.png",
                base_dir / "macd" / "macd_seasonal.png",
            ],
        },
        {
            "title": "虚实盘比因子",
            "summary": base_dir / "virtual_ratio" / "latest_summary.md",
            "images": [
                base_dir / "virtual_ratio" / "virtual_real_ratio_seasonal.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_rolling_ic.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_group_returns.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_backtest_nav.png",
            ],
        },
        {
            "title": "5分钟偏度因子",
            "summary": base_dir / "intraday_skew" / "latest_summary.md",
            "images": [
                base_dir / "intraday_skew" / "intraday_skew_seasonal.png",
                base_dir / "intraday_skew" / "intraday_skew_rolling_ic.png",
                base_dir / "intraday_skew" / "intraday_skew_group_returns.png",
                base_dir / "intraday_skew" / "intraday_skew_backtest_nav.png",
            ],
        },
        {
            "title": "展期+虚实盘组合因子",
            "summary": base_dir / "roll_virtual_combo" / "latest_summary.md",
            "images": [
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_seasonal.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_rolling_ic.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_group_returns.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_backtest_nav.png",
            ],
        },
        {
            "title": "持仓-价格联动因子",
            "summary": base_dir / "position_flow" / "latest_summary.md",
            "images": [
                base_dir / "position_flow" / "position_price_flow_seasonal.png",
                base_dir / "position_flow" / "position_price_flow_rolling_ic.png",
                base_dir / "position_flow" / "position_price_flow_group_returns.png",
                base_dir / "position_flow" / "position_price_flow_backtest_nav.png",
            ],
        },
    ]


def _manual_section_tex() -> str:
    chunks = [r"\section{因子手册与公式说明}"]
    for entry in FACTOR_MANUAL_ENTRIES:
        chunks.append(rf"\subsection{{{_escape_latex(entry['name'])}}}")
        chunks.append(r"\paragraph{公式}")
        chunks.append(r"\begin{itemize}")
        for formula in entry.get("formula_tex", []):
            chunks.append(rf"\item {formula}")
        chunks.append(r"\end{itemize}")
        chunks.append(r"\paragraph{变量定义}")
        chunks.append(r"\begin{itemize}")
        for definition in entry.get("definitions", []):
            chunks.append(rf"\item {definition}")
        chunks.append(r"\end{itemize}")
        chunks.append(r"\paragraph{业务含义}")
        chunks.append(r"\begin{itemize}")
        for logic in entry.get("logic", []):
            chunks.append(rf"\item {logic}")
        chunks.append(r"\end{itemize}")
    return "\n".join(chunks)


def _methodology_tex() -> str:
    return textwrap.dedent(
        r"""
        \section{研究方法与系统说明}
        \subsection{数据来源与刷新机制}
        \begin{itemize}
        \item 历史日线主库使用 Tushare，负责全合约历史、主力切换、阈值标定、IC 与回测分析。
        \item 实时快照使用同花顺，负责盘中价格、成交量、持仓量、虚实盘比和持仓联动信号。
        \item 宏观情绪扩展使用 FRED，主要用于 VIX 系列策略研究。
        \item 系统会优先读取本地缓存；若缓存落后于数据源最新可用交易日，则自动增量更新后再计算因子。
        \end{itemize}

        \subsection{历史分位数与阈值选择}
        \begin{itemize}
        \item 展期收益率因子默认采用全历史固定分位数阈值。
        \item 当前默认配置为：10\% 分位作为做多阈值，90\% 分位作为做空阈值。
        \item 这样做的目的是只在极端贴水或极端升水区域触发方向判断，减少中性区间噪声。
        \item 系统也保留滚动分位数阈值接口，可按 252 日窗口动态更新阈值。
        \end{itemize}

        \subsection{交易信号与解释逻辑}
        \begin{itemize}
        \item 展期收益率：贴水更深通常偏多，升水更深通常偏空。
        \item 动量：价格趋势延续时偏向顺势，趋势减弱时更多体现震荡或反转。
        \item MACD：金叉、死叉、柱体放大和收敛用于识别趋势拐点与强弱变化。
        \item 虚实盘比：高换手偏向短线博弈，低虚实盘比且增仓更像趋势资金沉淀。
        \item 持仓联动：价格与持仓增减组合判断多头增仓、空头增仓、空头回补和多头离场。
        \item 5分钟偏度：从日内收益分布的不对称性识别短期情绪尾部。
        \item 组合因子：要求多个底层因子形成共振，避免单一信号误判。
        \end{itemize}

        \subsection{因子回测与评估逻辑}
        \begin{itemize}
        \item IC（Information Coefficient）衡量因子值与未来收益的相关性，当前默认展示 1/3/5/10/20 日周期。
        \item 滚动 IC 使用 60 日窗口，用于观察因子稳定性与阶段性失效。
        \item 分组收益把样本按因子值分成 5 组，比较不同分组未来收益表现。
        \item 分位数组合回测使用上下分位阈值形成多空或多空仓位，并按固定持有期滚动计算净值。
        \item 当前主展示持有期为 3 日，辅助展示 5/10/20 日周期。
        \item 超额收益定义为：策略累计收益减去基准买入持有累计收益。
        \item 因子准确率常用 |5日IC| 近似观察；但高 IC 不必然对应高策略收益，因此同时展示超额收益和净值曲线。
        \end{itemize}

        \subsection{策略扩展模块}
        \begin{itemize}
        \item VIX + RSI 恐慌反转策略把价格超卖和情绪抬升同时作为入场条件。
        \item 开仓条件示例：RSI 进入超卖区域且 VIX 的 Z 分数显著高于近期均值。
        \item 平仓条件示例：RSI 回升、VIX 回落至均值附近或持有天数达到上限。
        \item 该模块目前既研究标普500，也研究沪镍主力连续，便于比较风险情绪在不同资产上的传播效果。
        \end{itemize}
        """
    ).strip()


def _quantile_table_tex(product_code: str) -> str:
    product_name = PRODUCT_CONFIG[product_code]["name"]
    file_path = PROCESSED_DATA_DIR / f"{product_code.lower()}_roll_yield_weighted_avg.csv"
    if not file_path.exists():
        return ""

    df = pd.read_csv(file_path)
    ry = df["roll_yield"].dropna()
    quantiles = {
        "5%": ry.quantile(0.05),
        "10%": ry.quantile(0.10),
        "25%": ry.quantile(0.25),
        "50%": ry.quantile(0.50),
        "75%": ry.quantile(0.75),
        "90%": ry.quantile(0.90),
        "95%": ry.quantile(0.95),
    }
    lines = [
        rf"\subsubsection{{{product_name} 历史分位数}}",
        r"\begin{center}",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r"样本数 & 均值 & 5\% & 10\% & 25\% & 50\% & 75\% & 90\% \\",
        r"\midrule",
        (
            f"{len(ry)} & {ry.mean()*100:.2f}\\% & {quantiles['5%']*100:.2f}\\% & "
            f"{quantiles['10%']*100:.2f}\\% & {quantiles['25%']*100:.2f}\\% & "
            f"{quantiles['50%']*100:.2f}\\% & {quantiles['75%']*100:.2f}\\% & "
            f"{quantiles['90%']*100:.2f}\\% \\\\"
        ),
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{center}",
    ]
    return "\n".join(lines)


def _product_snapshot_table_tex(product_code: str) -> str:
    base_dir = PROCESSED_DATA_DIR / product_code.lower()
    rows = []
    for title, rel in [
        ("展期收益率", "latest_summary.md"),
        ("价格动量", "momentum/latest_summary.md"),
        ("MACD", "macd/latest_summary.md"),
        ("虚实盘比", "virtual_ratio/latest_summary.md"),
        ("5分钟偏度", "intraday_skew/latest_summary.md"),
        ("展期+虚实盘组合", "roll_virtual_combo/latest_summary.md"),
        ("持仓-价格联动", "position_flow/latest_summary.md"),
    ]:
        summary = _read_summary_kv(base_dir / rel)
        signal = summary.get("交易信号", summary.get("当前信号", summary.get("趋势标签", "--")))
        interpretation = summary.get("信号解读", summary.get("当前趋势", "--"))
        rows.append((title, signal, interpretation))

    lines = [
        r"\subsection{最新因子状态总览}",
        r"\begin{longtable}{p{0.24\linewidth}p{0.18\linewidth}p{0.46\linewidth}}",
        r"\toprule",
        r"因子 & 当前信号 & 解释 \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"因子 & 当前信号 & 解释 \\",
        r"\midrule",
        r"\endhead",
    ]
    for title, signal, interpretation in rows:
        lines.append(
            f"{_escape_latex(title)} & {_escape_latex(str(signal))} & {_escape_latex(str(interpretation))} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{longtable}"])
    return "\n".join(lines)


def _score_signal(signal: str) -> int:
    text = str(signal)
    bullish_tokens = ["bullish", "uptrend", "strong_uptrend", "long_buildup", "short_covering", "+1", "多头增仓", "空头回补", "上行", "强上行"]
    bearish_tokens = ["bearish", "downtrend", "strong_downtrend", "short_buildup", "long_unwinding", "-1", "空头增仓", "多头离场", "下行", "强下行"]
    if any(token in text for token in bullish_tokens):
        return 1
    if any(token in text for token in bearish_tokens):
        return -1
    return 0


def _leader_summary_table_tex() -> str:
    summary_csv = PROCESSED_DATA_DIR / "summary" / "latest_factor_summary.csv"
    comparison_csv = PROCESSED_DATA_DIR / "comparison" / "factor_product_comparison.csv"
    if not summary_csv.exists():
        return ""

    df = pd.read_csv(summary_csv)
    if df.empty:
        return ""

    compare_df = pd.read_csv(comparison_csv) if comparison_csv.exists() else pd.DataFrame()
    best_factor_map: dict[str, str] = {}
    factor_label_map = {
        "roll_yield": "展期收益率",
        "momentum": "价格动量",
        "virtual_real_ratio": "虚实盘比",
        "intraday_skew": "5分钟偏度",
        "roll_virtual_combo": "展期+虚实盘组合",
        "macd": "MACD",
        "position_price_flow": "持仓-价格联动",
    }
    if not compare_df.empty:
        tmp = compare_df.sort_values(["product", "abs_ic_5d"], ascending=[True, False]).drop_duplicates("product")
        best_factor_map = {
            str(row["product"]).upper(): f"{factor_label_map.get(str(row['factor']), str(row['factor']))} ({row['abs_ic_5d']*100:.1f}%)"
            for _, row in tmp.iterrows()
        }

    table_rows = []
    positive_count = 0
    negative_count = 0
    for _, row in df.iterrows():
        product_code = str(row["代码"]).upper()
        base_dir = PROCESSED_DATA_DIR / product_code.lower()

        combo_summary = _read_summary_kv(base_dir / "roll_virtual_combo" / "latest_summary.md")
        intraday_summary = _read_summary_kv(base_dir / "intraday_skew" / "latest_summary.md")

        scores = [
            _score_signal(str(row.get("动量趋势", ""))),
            _score_signal(str(row.get("MACD趋势", ""))),
            _score_signal(str(row.get("持仓联动", ""))),
            _score_signal(str(combo_summary.get("交易信号", ""))),
            _score_signal(str(intraday_summary.get("交易信号", ""))),
        ]
        total_score = sum(scores)
        if total_score >= 2:
            verdict = "偏多"
            action = "等待回调后偏多跟踪"
            positive_count += 1
        elif total_score <= -2:
            verdict = "偏空"
            action = "反弹后偏空观察"
            negative_count += 1
        else:
            verdict = "中性"
            action = "以观察和择时为主"

        core_driver = (
            f"展期 {row.get('展期收益率', '--')} / "
            f"动量 {row.get('动量趋势', '--')} / "
            f"MACD {row.get('MACD趋势', '--')}"
        )
        risk_note = combo_summary.get("信号解读", intraday_summary.get("信号解读", "--"))
        best_factor = best_factor_map.get(product_code, "--")

        table_rows.append(
            (
                _escape_latex(str(row["品种"])),
                _escape_latex(str(row["历史最新日期"])),
                _escape_latex(verdict),
                _escape_latex(core_driver),
                _escape_latex(best_factor),
                _escape_latex(action),
                _escape_latex(risk_note),
            )
        )

    neutral_count = len(df) - positive_count - negative_count
    header = textwrap.dedent(
        rf"""
        \section{{管理层汇总页}}
        \subsection{{一页结论}}
        \begin{{center}}
        \begin{{tabular}}{{p{{0.18\linewidth}}p{{0.12\linewidth}}p{{0.10\linewidth}}p{{0.18\linewidth}}p{{0.14\linewidth}}p{{0.12\linewidth}}p{{0.14\linewidth}}}}
        \toprule
        品种 & 日期 & 结论 & 当前驱动 & 相对更强因子 & 建议动作 & 风险提示 \\
        \midrule
        """
    ).strip()

    body = "\n".join(" & ".join(row) + r" \\" for row in table_rows)
    footer = textwrap.dedent(
        rf"""
        \bottomrule
        \end{{tabular}}
        \end{{center}}

        \subsection{{一句话概览}}
        \begin{{itemize}}
        \item 当前跟踪品种共 {len(df)} 个，其中偏多 {positive_count} 个、偏空 {negative_count} 个、中性 {neutral_count} 个。
        \item 结论优先综合展期结构、价格趋势、MACD、持仓联动和组合因子，不等同于单一交易指令。
        \item 建议将“相对更强因子”视为后续重点跟踪方向，将“风险提示”视为当前最需要向领导解释的变化来源。
        \end{{itemize}}
        """
    ).strip()
    return "\n".join([header, body, footer])


def _factor_summary_tex(title: str, summary_path: Path) -> str:
    lines = _read_markdown_lines(summary_path)
    body = [rf"\subsection{{{_escape_latex(title)}}}"]
    if not lines:
        body.append("当前未找到对应摘要文件。")
        return "\n".join(body)
    body.append(_itemize(lines[1:] if lines and not lines[0].startswith("日期") else lines))
    return "\n".join(body)


def _image_tex(image_path: Path, caption: str) -> str:
    if not image_path.exists():
        return ""
    return textwrap.dedent(
        rf"""
        \begin{{figure}}[p]
        \centering
        \includegraphics[width=\linewidth,height=0.82\textheight,keepaspectratio]{{{image_path.as_posix()}}}
        \caption{{{_escape_latex(caption)}}}
        \end{{figure}}
        \clearpage
        """
    ).strip()


def _product_section_tex(product_code: str) -> str:
    product_name = PRODUCT_CONFIG[product_code]["name"]
    base_dir = PROCESSED_DATA_DIR / product_code.lower()
    chunks = [rf"\section{{{product_name} 专题}}"]
    chunks.append(_product_snapshot_table_tex(product_code))
    chunks.append(_quantile_table_tex(product_code))
    for section in _factor_sections(base_dir):
        chunks.append(_factor_summary_tex(section["title"], section["summary"]))
        for image in section["images"]:
            chunks.append(_image_tex(image, f"{product_name} - {section['title']}"))
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _strategy_section_tex() -> str:
    chunks = [r"\section{策略扩展研究}"]
    strategies = [
        ("VIX + 标普500 恐慌反转策略", PROCESSED_DATA_DIR / "vix_panic_reversion"),
        ("VIX + 沪镍 恐慌反转策略", PROCESSED_DATA_DIR / "ni_vix_panic_reversion"),
    ]
    for title, base_dir in strategies:
        chunks.append(_factor_summary_tex(title, base_dir / "latest_summary.md"))
        chunks.append(_image_tex(base_dir / "backtest_chart.png", title))
    return "\n\n".join(chunk for chunk in chunks if chunk)


def _comparison_section_tex() -> str:
    base = PROCESSED_DATA_DIR / "comparison"
    chunks = [r"\section{对比研究与附加实验}"]
    report_md = base / "factor_product_comparison.md"
    if report_md.exists():
        chunks.append(r"\subsection{品种影响对比}")
        chunks.append(_itemize(_read_markdown_lines(report_md)))
        chunks.append(_image_tex(base / "factor_abs_ic5d_comparison.png", "不同品种下各因子准确率对比"))
        chunks.append(_image_tex(base / "factor_excess_return_comparison.png", "不同品种下各因子超额收益对比"))

    denoise_md = base / "denoise" / "denoise_comparison_report.md"
    if denoise_md.exists():
        chunks.append(r"\subsection{MACD 降噪实验}")
        chunks.append(_itemize(_read_markdown_lines(denoise_md)))
        chunks.append(_image_tex(base / "denoise" / "denoise_abs_ic5d_comparison.png", "降噪前后准确率对比"))
        chunks.append(_image_tex(base / "denoise" / "denoise_excess_return_comparison.png", "降噪前后超额收益对比"))

    vix_cmp = base / "vix_strategy_product_comparison.md"
    if vix_cmp.exists():
        chunks.append(r"\subsection{VIX 策略跨标的对比}")
        chunks.append(_itemize(_read_markdown_lines(vix_cmp)))
        chunks.append(_image_tex(base / "vix_strategy_product_comparison.png", "VIX 策略跨标的对比"))

    vix_cmp_rev = base / "vix_strategy_product_comparison_reverse.md"
    if vix_cmp_rev.exists():
        chunks.append(r"\subsection{VIX 反向策略对比}")
        chunks.append(_itemize(_read_markdown_lines(vix_cmp_rev)))
        chunks.append(_image_tex(base / "vix_strategy_product_comparison_reverse.png", "VIX 反向策略对比"))
    return "\n\n".join(chunk for chunk in chunks if chunk)


def export_comprehensive_report(product: str = "ALL", output_dir: Path | None = None) -> Path:
    """导出综合 LaTeX 总报告。"""
    product = product.upper()
    report_dir = output_dir or PROCESSED_DATA_DIR
    build_dir = report_dir / "latex_comprehensive_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    tex_path = build_dir / "comprehensive_report.tex"

    if product == "ALL":
        products = _product_codes("ALL")
        title = "期货研究综合总报告"
        pdf_target = report_dir / "summary" / "comprehensive_report.pdf"
    else:
        products = _product_codes(product)
        title = f"{PRODUCT_CONFIG[product]['name']} 综合研究报告"
        pdf_target = report_dir / product.lower() / f"{product.lower()}_comprehensive_report.pdf"
    pdf_target.parent.mkdir(parents=True, exist_ok=True)

    product_sections = "\n\n".join(_product_section_tex(code) for code in products)
    leader_summary = _leader_summary_table_tex()
    content = textwrap.dedent(
        rf"""
        \documentclass[11pt,a4paper]{{ctexart}}
        \usepackage[margin=2cm]{{geometry}}
        \usepackage{{amsmath,amssymb,booktabs,longtable,tabularx,array,graphicx,float,hyperref}}
        \usepackage{{fancyhdr}}
        \usepackage{{titlesec}}
        \usepackage{{setspace}}
        \setstretch{{1.15}}
        \pagestyle{{fancy}}
        \fancyhf{{}}
        \fancyfoot[C]{{\thepage}}
        \titleformat{{\section}}{{\Large\bfseries}}{{\thesection}}{{0.8em}}{{}}
        \titleformat{{\subsection}}{{\large\bfseries}}{{\thesubsection}}{{0.6em}}{{}}
        \title{{{_escape_latex(title)}}}
        \author{{nickel\_research}}
        \date{{{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}
        \begin{{document}}
        \maketitle
        \tableofcontents
        \clearpage
        \section{{报告说明}}
        \begin{{itemize}}
        \item 本报告把当前系统中的因子手册、方法论、历史分位数、阈值选择、交易信号解释、因子回测逻辑、超额收益定义、各品种结果图表和策略扩展统一合并到一个文件中。
        \item 因子与策略图表均来自系统最新一次从原始数据重新计算后的导出结果，而不是旧图的拼接。
        \item 当前覆盖品种包括：{_escape_latex("、".join(PRODUCT_CONFIG[code]["name"] for code in products))}。
        \end{{itemize}}
        {leader_summary}
        {_methodology_tex()}
        {_manual_section_tex()}
        {product_sections}
        {_strategy_section_tex()}
        {_comparison_section_tex()}
        \end{{document}}
        """
    ).strip() + "\n"
    tex_path.write_text(content, encoding="utf-8")

    xelatex = shutil.which("xelatex")
    if not xelatex:
        raise RuntimeError("未找到 xelatex，无法生成综合报告")

    for _ in range(2):
        subprocess.run(
            [xelatex, "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=build_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    shutil.copy2(build_dir / "comprehensive_report.pdf", pdf_target)
    return pdf_target

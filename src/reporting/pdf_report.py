"""将研究结果导出为可打印 PDF。"""

from __future__ import annotations

import math
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

import matplotlib.image as mpimg
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

from config.settings import PROCESSED_DATA_DIR, PRODUCT_CONFIG
from src.plotting import setup_chinese_font

setup_chinese_font()

PAGE_SIZE = (8.27, 11.69)
PAGE_BG = "#ffffff"
PANEL_BG = "#ffffff"
ACCENT = "#222222"
TEXT = "#222222"
MUTED = "#666666"


FACTOR_EXPLANATIONS = {
    "roll_yield": {
        "title": "展期收益率因子",
        "description": (
            "通过比较近月和远月合约价格，判断期限结构处于升水还是贴水。"
            "负值通常对应 backwardation，往往意味着现货偏紧；正值通常对应 contango，"
            "往往意味着供给更宽松。"
        ),
    },
    "momentum": {
        "title": "动量因子",
        "description": (
            "用近一段时间的价格变化衡量趋势是否延续。动量为正且趋势强时，"
            "更偏向顺势；动量转弱时，更适合观察趋势衰减或震荡。"
        ),
    },
    "macd": {
        "title": "MACD 因子",
        "description": (
            "通过 DIF、DEA 和柱状图观察趋势强弱与拐点。适合识别金叉、死叉以及"
            "趋势加速或减速的阶段。"
        ),
    },
    "virtual_ratio": {
        "title": "虚实盘比因子",
        "description": (
            "用成交量和持仓量的关系判断市场更偏短线换手还是增仓沉淀。虚实盘比高，"
            "通常说明交易活跃但筹码沉淀有限；虚实盘比较低，则更可能体现增仓趋势。"
        ),
    },
    "intraday_skew": {
        "title": "5分钟偏度因子",
        "description": (
            "用日内 5 分钟收益率分布的偏度衡量价格路径是否存在明显的不对称。"
            "偏度显著偏高时，更像冲高后的拥挤交易；偏度显著偏低时，更像恐慌后的超跌状态。"
        ),
    },
    "roll_virtual_combo": {
        "title": "展期 + 虚实盘组合因子",
        "description": (
            "把展期收益率和虚实盘比标准化后加权合成，重点识别期限结构与成交持仓结构"
            "是否形成同向共振。"
        ),
    },
    "position_flow": {
        "title": "持仓-价格联动因子",
        "description": (
            "把价格涨跌和持仓增减组合起来，识别多头增仓、空头增仓、空头回补与多头离场。"
        ),
    },
    "strategy": {
        "title": "VIX + RSI 策略",
        "description": (
            "把价格超卖和风险情绪抬升结合起来，寻找恐慌后的反转机会。"
            "报告中会展示最新状态摘要和净值图，方便直接汇报。"
        ),
    },
}

FACTOR_MANUAL_ENTRIES = [
    {
        "name": "展期收益率因子",
        "formula_tex": [
            r"$R_t=\dfrac{\ln(P_{near})-\ln(P_{far})}{T_{far}-T_{near}}\times 365$",
        ],
        "definitions": [
            r"$P_{near}, P_{far}$: 近月和远月合约价格。",
            r"$T_{far}, T_{near}$: 两个合约到期日的间隔天数，用于期限归一化。",
        ],
        "logic": [
            r"$R_t$ 较高时，通常对应远月贴水、现货偏紧，价格更容易上行。",
            r"$R_t$ 较低时，通常对应远月升水、供应宽松，价格更容易承压。",
        ],
    },
    {
        "name": "价格动量因子",
        "formula_tex": [
            r"$Momentum_t=\dfrac{Close_t}{Close_{t-N}}-1$",
            r"$TrendStrength_t=\dfrac{MA_{short}}{MA_{long}}-1$",
        ],
        "definitions": [
            r"$Close_t, Close_{t-N}$: 当前与 $N$ 日前收盘价。",
            r"$MA_{short}, MA_{long}$: 短周期和长周期均线。",
        ],
        "logic": [
            r"$Momentum_t>0$ 且 $TrendStrength_t>0$ 时，通常表示上涨趋势延续。",
            r"$Momentum_t<0$ 且 $TrendStrength_t<0$ 时，通常表示下跌趋势延续。",
        ],
    },
    {
        "name": "MACD 因子",
        "formula_tex": [
            r"$DIF=EMA_{12}(Close)-EMA_{26}(Close)$",
            r"$DEA=EMA_{9}(DIF)$",
            r"$MACD\ Histogram=2\times(DIF-DEA)$",
        ],
        "definitions": [
            r"$EMA_{12}, EMA_{26}$: 快线与慢线指数移动平均。",
            r"$DIF, DEA$: 快慢线差值及其平滑线。",
        ],
        "logic": [
            r"$DIF$ 上穿 $DEA$ 常被视为金叉，趋势偏多。",
            r"$DIF$ 下穿 $DEA$ 常被视为死叉，趋势偏空。",
            r"$MACD\ Histogram$ 扩大表示动能增强，收敛表示动能减弱。",
        ],
    },
    {
        "name": "虚实盘比因子",
        "formula_tex": [
            r"$VRR=\dfrac{Volume}{OpenInterest}$",
        ],
        "definitions": [
            r"$Volume, OpenInterest$: 成交量与持仓量。",
            r"$VRR$ 越高，表示单位持仓对应的换手越频繁。",
        ],
        "logic": [
            r"$VRR$ 偏高时，通常表示短线资金活跃、博弈更强。",
            r"$VRR$ 较低且增仓时，通常表示筹码沉淀、趋势资金更稳定。",
        ],
    },
    {
        "name": "持仓-价格联动因子",
        "formula_tex": [
            r"$PriceChange_t=\dfrac{Close_t}{Close_{t-1}}-1$",
            r"$OIChange_t=\dfrac{OI_t-OI_{t-1}}{OI_{t-1}}$",
        ],
        "definitions": [
            r"$Close_t, Close_{t-1}$: 当日与前一日收盘价。",
            r"$OI_t, OI_{t-1}$: 当日与前一日持仓量。",
        ],
        "logic": [
            r"$PriceChange_t>0$ 且 $OIChange_t>0$ 时，通常表示多头增仓。",
            r"$PriceChange_t<0$ 且 $OIChange_t>0$ 时，通常表示空头增仓。",
            r"$PriceChange_t>0$ 且 $OIChange_t<0$ 时，通常表示空头回补。",
            r"$PriceChange_t<0$ 且 $OIChange_t<0$ 时，通常表示多头离场。",
        ],
    },
    {
        "name": "5分钟偏度因子",
        "formula_tex": [
            r"$skew_t=E\left[\left(\dfrac{ret_i-\mu_{5min}}{\sigma_{5min}}\right)^3\right]$",
        ],
        "definitions": [
            r"$ret_i$: 回看期内商品期货的 5 分钟收益率序列。",
            r"$\mu_{5min}$: 回看期内所有 5 分钟收益率的均值。",
            r"$\sigma_{5min}$: 回看期内所有 5 分钟收益率的标准差。",
        ],
        "logic": [
            r"$skew_t$ 显著偏高时，通常表示价格上行尾部更长，短期更容易在情绪回落后承压。",
            r"$skew_t$ 显著偏低时，通常表示价格下行尾部更长，恐慌释放后更容易出现反弹。",
            r"把 $ret_i$ 拆成正收益与负收益子样本，还可以得到上行偏度和下行偏度。",
        ],
    },
    {
        "name": "RSI 指标",
        "formula_tex": [
            r"$RSI=100-\dfrac{100}{1+RS}$",
            r"$RS=\dfrac{AvgGain_n}{AvgLoss_n}$",
        ],
        "definitions": [
            r"$AvgGain_n, AvgLoss_n$: 过去 $n$ 个周期平均上涨与下跌幅度。",
            r"$RSI$ 数值通常位于 $0$ 到 $100$ 之间。",
        ],
        "logic": [
            r"$RSI$ 越低，通常表示价格越接近短期超卖。",
            r"$RSI$ 越高，通常表示价格越接近短期超买。",
        ],
    },
    {
        "name": "VIX 情绪因子",
        "formula_tex": [
            r"$VIX_z=\dfrac{VIX-\mu_n(VIX)}{\sigma_n(VIX)}$",
        ],
        "definitions": [
            r"$\mu_n(VIX)$: $VIX$ 在过去 $n$ 日的均值。",
            r"$\sigma_n(VIX)$: $VIX$ 在过去 $n$ 日的标准差。",
        ],
        "logic": [
            r"$VIX_z$ 越高，表示当前恐慌显著高于近期常态。",
            r"$VIX_z$ 更适合作为情绪过滤器，而不是单独方向信号。",
        ],
    },
    {
        "name": "VIX + RSI 恐慌反转策略",
        "formula_tex": [
            r"$Entry:\ RSI \leq 30,\ \ VIX_z \geq 1.0$",
            r"$Exit:\ RSI \geq 55\ \mathrm{or}\ VIX \leq \mu_n(VIX)\ \mathrm{or}\ HoldingDays \geq 10$",
            r"$StrategyReturn_t=Position_{t-1}\times Return_t$",
        ],
        "definitions": [
            r"$Entry$: $RSI$ 跌入超卖且 $VIX_z$ 显著升高时开仓。",
            r"$Exit$: 反弹兑现、恐慌缓解或持仓超过上限时平仓。",
        ],
        "logic": [
            r"只有 $RSI$ 超卖和 $VIX_z$ 抬升同时出现，才认为反转信号更有效。",
            r"$StrategyReturn_t$ 本质上是用情绪过滤后的价格反转收益。",
        ],
    },
]


def _get_product_name(product: str) -> str:
    return PRODUCT_CONFIG.get(product.upper(), {}).get("name", product.upper())


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


def _wrap_lines(lines: Sequence[str], width: int = 34) -> List[str]:
    wrapped: List[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        chunks = textwrap.wrap(line, width=width) or [line]
        wrapped.extend(chunks)
    return wrapped


def _wrap_cell_text(value: object, width: int) -> str:
    text = str(value)
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def _new_page() -> tuple[plt.Figure, plt.Axes]:
    fig = plt.figure(figsize=PAGE_SIZE, facecolor=PAGE_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    return fig, ax


def _draw_page_shell(fig: plt.Figure, title: str, subtitle: str | None = None) -> None:
    fig.patches.extend(
        [
            patches.Rectangle((0, 0), 1, 1, transform=fig.transFigure, facecolor=PAGE_BG, edgecolor="none", zorder=-10),
            patches.Rectangle((0.06, 0.06), 0.88, 0.88, transform=fig.transFigure, facecolor=PANEL_BG, edgecolor="#dddddd", linewidth=1.0, zorder=-9),
            patches.Rectangle((0.06, 0.90), 0.88, 0.04, transform=fig.transFigure, facecolor=ACCENT, edgecolor="none", zorder=-8),
        ]
    )
    fig.text(0.09, 0.865, title, fontsize=20, fontweight="bold", color=TEXT, va="top")
    if subtitle:
        fig.text(0.09, 0.835, subtitle, fontsize=10.5, color=MUTED, va="top")


def _add_footer(fig: plt.Figure, footer: str) -> None:
    fig.text(0.09, 0.075, footer, fontsize=9, color=MUTED, va="bottom")


def _render_text_page(
    pdf: PdfPages,
    title: str,
    lines: Sequence[str],
    footer: str | None = None,
    subtitle: str | None = None,
) -> None:
    fig, _ = _new_page()
    _draw_page_shell(fig, title, subtitle)

    y = 0.79
    for line in _wrap_lines(lines):
        if not line:
            y -= 0.014
            continue
        fig.text(0.10, y, line, fontsize=11.2, color=TEXT, va="top")
        y -= 0.027
        if y < 0.08:
            break

    if footer:
        _add_footer(fig, footer)

    pdf.savefig(fig)
    plt.close(fig)


def _clean_signal_text(value: str) -> str:
    mapping = {
        "sideways": "震荡",
        "uptrend": "上行",
        "strong_uptrend": "强上行",
        "downtrend": "下行",
        "strong_downtrend": "强下行",
        "contango": "升水",
        "backwardation": "贴水",
        "neutral": "中性",
        "long_buildup": "多头增仓",
        "short_buildup": "空头增仓",
        "short_covering": "空头回补",
        "long_unwinding": "多头离场",
    }
    return mapping.get(str(value), str(value))


def _render_product_overview_table(pdf: PdfPages, summary_csv: Path) -> None:
    fig, _ = _new_page()
    _draw_page_shell(fig, "多品种总览", "核心因子状态一页对比，适合打印汇报时快速浏览。")

    if not summary_csv.exists():
        _add_footer(fig, f"未找到汇总表: {summary_csv}")
        pdf.savefig(fig)
        plt.close(fig)
        return

    df = pd.read_csv(summary_csv)
    if df.empty:
        _add_footer(fig, f"汇总表为空: {summary_csv}")
        pdf.savefig(fig)
        plt.close(fig)
        return

    display_primary = pd.DataFrame(
        {
            "品种": df["品种"],
            "日期": df["历史最新日期"],
            "展期": df["展期收益率"].astype(str) + " / " + df["实时展期信号"].map(_clean_signal_text).astype(str),
            "动量": df["动量趋势"].map(_clean_signal_text).astype(str) + " / " + df["动量信号"].astype(str),
            "MACD": df["MACD趋势"].map(_clean_signal_text).astype(str) + " / " + df["MACD持仓"].astype(str),
            "虚实盘": df["虚实盘比"].astype(str) + " / " + df["虚实盘信号"].map(_clean_signal_text).astype(str),
            "持仓联动": df["持仓联动"].map(_clean_signal_text).astype(str),
        }
    )

    intraday_values = []
    combo_values = []
    for _, row in df.iterrows():
        code = str(row["代码"]).lower()
        base_dir = summary_csv.parent.parent / code
        intraday_summary = _read_summary_kv(base_dir / "intraday_skew" / "latest_summary.md")
        combo_summary = _read_summary_kv(base_dir / "roll_virtual_combo" / "latest_summary.md")
        intraday_values.append(
            f"{intraday_summary.get('偏度因子', '--')} / {_clean_signal_text(intraday_summary.get('交易信号', '--'))}"
        )
        combo_values.append(
            f"{combo_summary.get('组合得分', '--')} / {_clean_signal_text(combo_summary.get('交易信号', '--'))}"
        )

    display_secondary = pd.DataFrame(
        {
            "品种": df["品种"],
            "5分钟偏度": intraday_values,
            "组合因子": combo_values,
            "偏度解读": [
                _read_summary_kv(summary_csv.parent.parent / str(code).lower() / "intraday_skew" / "latest_summary.md").get("信号解读", "--")
                for code in df["代码"]
            ],
            "组合解读": [
                _read_summary_kv(summary_csv.parent.parent / str(code).lower() / "roll_virtual_combo" / "latest_summary.md").get("信号解读", "--")
                for code in df["代码"]
            ],
        }
    )
    display_secondary["偏度解读"] = display_secondary["偏度解读"].map(lambda x: _wrap_cell_text(x, 16))
    display_secondary["组合解读"] = display_secondary["组合解读"].map(lambda x: _wrap_cell_text(x, 16))
    display_secondary["5分钟偏度"] = display_secondary["5分钟偏度"].map(lambda x: _wrap_cell_text(x, 10))
    display_secondary["组合因子"] = display_secondary["组合因子"].map(lambda x: _wrap_cell_text(x, 10))

    col_labels = list(display_primary.columns)
    cell_text = display_primary.values.tolist()
    col_widths = [0.10, 0.12, 0.18, 0.15, 0.16, 0.14, 0.15]

    ax_table_1 = fig.add_axes([0.08, 0.56, 0.84, 0.18])
    ax_table_1.axis("off")
    table = ax_table_1.table(
        cellText=cell_text,
        colLabels=col_labels,
        colWidths=col_widths,
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.2)
    table.scale(1, 1.8)

    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d9d9d9")
        cell.set_linewidth(0.7)
        if row == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(weight="bold", color=TEXT)
        else:
            cell.set_facecolor("#ffffff" if row % 2 == 1 else "#fbfbfb")

    col_labels_2 = list(display_secondary.columns)
    cell_text_2 = display_secondary.values.tolist()
    col_widths_2 = [0.10, 0.16, 0.16, 0.29, 0.29]

    ax_table_2 = fig.add_axes([0.08, 0.29, 0.84, 0.18])
    ax_table_2.axis("off")
    table2 = ax_table_2.table(
        cellText=cell_text_2,
        colLabels=col_labels_2,
        colWidths=col_widths_2,
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table2.auto_set_font_size(False)
    table2.set_fontsize(8.0)
    table2.scale(1, 2.7)

    for (row, col), cell in table2.get_celld().items():
        cell.set_edgecolor("#d9d9d9")
        cell.set_linewidth(0.7)
        if row == 0:
            cell.set_facecolor("#f2f2f2")
            cell.set_text_props(weight="bold", color=TEXT)
        else:
            cell.set_facecolor("#ffffff" if row % 2 == 1 else "#fbfbfb")
            if col >= 3:
                cell.set_text_props(ha="left", va="center")

    fig.text(0.10, 0.24, "重点解读", fontsize=12.5, fontweight="bold", color=TEXT, va="top")

    y = 0.205
    for _, row in df.iterrows():
        line = (
            f"{row['品种']}：展期 {row['展期收益率']}，动量 {_clean_signal_text(row['动量趋势'])}，"
            f"MACD {_clean_signal_text(row['MACD趋势'])}，持仓联动 {_clean_signal_text(row['持仓联动'])}。"
        )
        fig.text(0.10, y, f"- {line}", fontsize=10.2, color=TEXT, va="top")
        y -= 0.03
        if y < 0.10:
            break

    _add_footer(fig, f"汇总表来源: {summary_csv}")
    pdf.savefig(fig)
    plt.close(fig)


def _render_cover_page(pdf: PdfPages, title: str, subtitle_lines: Sequence[str]) -> None:
    fig, _ = _new_page()
    fig.patches.extend(
        [
            patches.Rectangle((0, 0), 1, 1, transform=fig.transFigure, facecolor="#ffffff", edgecolor="none", zorder=-10),
            patches.Rectangle((0.08, 0.10), 0.84, 0.80, transform=fig.transFigure, facecolor="#ffffff", edgecolor="#dddddd", linewidth=1.2, zorder=-9),
            patches.Rectangle((0.08, 0.78), 0.84, 0.12, transform=fig.transFigure, facecolor=ACCENT, edgecolor="none", zorder=-8),
        ]
    )
    fig.text(0.12, 0.70, title, fontsize=26, fontweight="bold", color=TEXT)
    fig.text(0.12, 0.64, "期货研究打印版报告", fontsize=13, color=MUTED)
    y = 0.54
    for line in subtitle_lines:
        fig.text(0.12, y, line, fontsize=12, color=TEXT)
        y -= 0.045

    pdf.savefig(fig)
    plt.close(fig)


def _render_toc_page(
    pdf: PdfPages,
    title: str,
    entries: Sequence[dict],
    footer: str | None = None,
    subtitle: str | None = None,
) -> None:
    fig, _ = _new_page()
    _draw_page_shell(fig, title, subtitle)

    y = 0.80
    for entry in entries:
        page_no = entry.get("page")
        page_text = f"{page_no}" if page_no is not None else ""
        label = entry.get("label", "")
        level = int(entry.get("level", 0))
        indent = 0.02 * level
        font_size = 12 if level == 0 else 10.8
        font_weight = "bold" if level == 0 else "normal"
        color = TEXT if level == 0 else "#333333"

        fig.text(0.10 + indent, y, label, fontsize=font_size, fontweight=font_weight, color=color, va="top")
        fig.text(0.88, y, page_text, fontsize=10.5, color=MUTED, va="top", ha="right")
        fig.lines.append(
            plt.Line2D(
                [0.10 + indent + 0.18, 0.85],
                [y - 0.008, y - 0.008],
                transform=fig.transFigure,
                color="#d8d8d8",
                linewidth=0.6,
                linestyle=(0, (1.5, 3)),
            )
        )
        y -= 0.032 if level == 0 else 0.026
        if y < 0.11:
            break

    if footer:
        _add_footer(fig, footer)

    pdf.savefig(fig)
    plt.close(fig)


def _draw_manual_entry_block(fig: plt.Figure, entry: dict, index: int, total: int, left: float, bottom: float, width: float, height: float) -> None:
    fig.patches.extend(
        [
            patches.Rectangle((left, bottom), width, height, transform=fig.transFigure, facecolor="#ffffff", edgecolor="#dddddd", linewidth=0.9, zorder=-7),
            patches.Rectangle((left + 0.02, bottom + height * 0.50), width - 0.04, height * 0.20, transform=fig.transFigure, facecolor="#fafafa", edgecolor="#e6e6e6", linewidth=0.8, zorder=-6),
            patches.Rectangle((left + 0.02, bottom + 0.03), width - 0.04, height * 0.38, transform=fig.transFigure, facecolor="#fcfcfc", edgecolor="#e6e6e6", linewidth=0.8, zorder=-6),
        ]
    )

    fig.text(left + 0.02, bottom + height - 0.03, entry["name"], fontsize=14, fontweight="bold", color=TEXT, va="top")
    fig.text(left + width - 0.02, bottom + height - 0.03, f"{index}/{total}", fontsize=9, color=MUTED, va="top", ha="right")

    fig.text(left + 0.03, bottom + height * 0.66, "公式", fontsize=10, fontweight="bold", color=TEXT, va="top")
    y = bottom + height * 0.60
    for formula in entry.get("formula_tex", []):
        fig.text(left + 0.03, y, formula, fontsize=12, color=TEXT, va="top")
        y -= 0.045

    y = bottom + height * 0.37
    explanation_lines = [*entry.get("definitions", []), *entry.get("logic", [])]
    for bullet in explanation_lines:
        fig.text(left + 0.03, y, f"- {bullet}", fontsize=9.2, color=TEXT, va="top")
        y -= 0.032
        if y < bottom + 0.04:
            break


def _render_manual_entries_page(pdf: PdfPages, entries: Sequence[dict], start_index: int, total: int) -> None:
    fig, _ = _new_page()
    _draw_page_shell(fig, "因子手册")
    positions = [
        (0.10, 0.52, 0.80, 0.32),
        (0.10, 0.14, 0.80, 0.32),
    ]
    for idx, entry in enumerate(entries):
        left, bottom, width, height = positions[idx]
        _draw_manual_entry_block(fig, entry, start_index + idx, total, left, bottom, width, height)

    _add_footer(fig, "因子手册页")
    pdf.savefig(fig)
    plt.close(fig)


def _get_image_dimensions(image_path: Path) -> tuple[int, int]:
    image = mpimg.imread(image_path)
    height, width = image.shape[:2]
    return width, height


def _draw_single_image_card(fig: plt.Figure, image_path: Path, left: float, bottom: float, width: float, height: float, caption: str) -> None:
    img_w, img_h = _get_image_dimensions(image_path)
    box_w = width
    box_h = height - 0.035
    scale = min(box_w / img_w, box_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    x = left + (width - draw_w) / 2
    y = bottom + (box_h - draw_h) / 2

    ax = fig.add_axes([x, y, draw_w, draw_h])
    ax.imshow(mpimg.imread(image_path), interpolation="nearest")
    ax.axis("off")

    fig.text(left, bottom + height + 0.008, caption, fontsize=10.2, color=TEXT, va="bottom", fontweight="bold")


def _render_image_gallery_page(
    pdf: PdfPages,
    title: str,
    image_paths: Sequence[Path],
    subtitle: str | None = None,
) -> None:
    images = [path for path in image_paths if path.exists()]
    if not images:
        return

    for start in range(0, len(images), 2):
        page_images = images[start : start + 2]
        fig, _ = _new_page()
        page_subtitle = subtitle if len(images) <= 2 else f"{subtitle}（第 {start // 2 + 1} 页）"
        _draw_page_shell(fig, title, page_subtitle)
        if len(page_images) == 1:
            _draw_single_image_card(fig, page_images[0], 0.09, 0.14, 0.82, 0.68, page_images[0].stem.replace("_", " "))
        else:
            _draw_single_image_card(fig, page_images[0], 0.09, 0.49, 0.82, 0.30, page_images[0].stem.replace("_", " "))
            _draw_single_image_card(fig, page_images[1], 0.09, 0.14, 0.82, 0.30, page_images[1].stem.replace("_", " "))

        _add_footer(fig, "图表直接贴图并按原始比例排版，减少边框和缩放干扰。")
        pdf.savefig(fig)
        plt.close(fig)


def _factor_section(
    pdf: PdfPages,
    title: str,
    explanation: str,
    summary_path: Path,
    image_paths: Iterable[Path],
) -> None:
    lines = [f"因子解释：{explanation}"]
    summary_lines = _read_markdown_lines(summary_path)
    if summary_lines:
        lines.extend(["", "最新摘要：", *summary_lines])
    else:
        lines.extend(["", "最新摘要：当前未找到对应摘要文件。"])

    _render_text_page(
        pdf,
        title,
        lines,
        footer=f"摘要来源: {summary_path}",
        subtitle="说明页包含因子逻辑与当前最新状态，下一页展示对应图表。",
    )
    _render_image_gallery_page(pdf, f"{title} 图表", list(image_paths), subtitle="图表页")


def _build_single_product_toc(product: str) -> List[dict]:
    entries: List[dict] = []
    page = 2
    entries.append({"label": "目录", "page": page, "level": 0})
    page += 1

    for section in _collect_product_sections(PROCESSED_DATA_DIR / product.lower()):
        entries.append({"label": section["title"], "page": page, "level": 0})
        entries.append({"label": "说明与最新摘要", "page": page, "level": 1})
        entries.append({"label": "图表页", "page": page + 1, "level": 1})
        page += 2

    strategy = _collect_strategy_section(PROCESSED_DATA_DIR, product)
    entries.append({"label": strategy["title"], "page": page, "level": 0})
    entries.append({"label": "说明与最新摘要", "page": page, "level": 1})
    entries.append({"label": "图表页", "page": page + 1, "level": 1})
    return entries


def _build_all_products_toc(products: Sequence[str]) -> List[dict]:
    entries: List[dict] = []
    page = 2
    entries.append({"label": "目录", "page": page, "level": 0})
    page += 1
    entries.append({"label": "多品种总览", "page": page, "level": 0})
    page += 1

    for product in products:
        entries.append({"label": f"{_get_product_name(product)} 专题", "page": page, "level": 0})
        for section in _collect_product_sections(PROCESSED_DATA_DIR / product.lower()):
            entries.append({"label": section["title"], "page": page, "level": 1})
            page += 2
        strategy = _collect_strategy_section(PROCESSED_DATA_DIR, product)
        entries.append({"label": strategy["title"], "page": page, "level": 1})
        page += 2

    return entries


def _collect_product_sections(base_dir: Path) -> List[dict]:
    return [
        {
            "title": FACTOR_EXPLANATIONS["roll_yield"]["title"],
            "description": FACTOR_EXPLANATIONS["roll_yield"]["description"],
            "summary": base_dir / "latest_summary.md",
            "images": [
                base_dir / "roll_yield_seasonal.png",
                base_dir / "roll_yield_rolling_ic.png",
                base_dir / "roll_yield_group_returns.png",
                base_dir / "roll_yield_backtest_nav.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["momentum"]["title"],
            "description": FACTOR_EXPLANATIONS["momentum"]["description"],
            "summary": base_dir / "momentum" / "latest_summary.md",
            "images": [
                base_dir / "momentum" / "momentum_seasonal.png",
                base_dir / "momentum" / "momentum_rolling_ic.png",
                base_dir / "momentum" / "momentum_group_returns.png",
                base_dir / "momentum" / "momentum_backtest_nav.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["macd"]["title"],
            "description": FACTOR_EXPLANATIONS["macd"]["description"],
            "summary": base_dir / "macd" / "latest_summary.md",
            "images": [
                base_dir / "macd" / "macd_chart.png",
                base_dir / "macd" / "macd_seasonal.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["virtual_ratio"]["title"],
            "description": FACTOR_EXPLANATIONS["virtual_ratio"]["description"],
            "summary": base_dir / "virtual_ratio" / "latest_summary.md",
            "images": [
                base_dir / "virtual_ratio" / "virtual_real_ratio_seasonal.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_rolling_ic.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_group_returns.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_backtest_nav.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["intraday_skew"]["title"],
            "description": FACTOR_EXPLANATIONS["intraday_skew"]["description"],
            "summary": base_dir / "intraday_skew" / "latest_summary.md",
            "images": [
                base_dir / "intraday_skew" / "intraday_skew_seasonal.png",
                base_dir / "intraday_skew" / "intraday_skew_rolling_ic.png",
                base_dir / "intraday_skew" / "intraday_skew_group_returns.png",
                base_dir / "intraday_skew" / "intraday_skew_backtest_nav.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["roll_virtual_combo"]["title"],
            "description": FACTOR_EXPLANATIONS["roll_virtual_combo"]["description"],
            "summary": base_dir / "roll_virtual_combo" / "latest_summary.md",
            "images": [
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_seasonal.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_rolling_ic.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_group_returns.png",
                base_dir / "roll_virtual_combo" / "roll_virtual_combo_backtest_nav.png",
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["position_flow"]["title"],
            "description": FACTOR_EXPLANATIONS["position_flow"]["description"],
            "summary": base_dir / "position_flow" / "latest_summary.md",
            "images": [
                base_dir / "position_flow" / "position_price_flow_seasonal.png",
                base_dir / "position_flow" / "position_price_flow_rolling_ic.png",
                base_dir / "position_flow" / "position_price_flow_group_returns.png",
                base_dir / "position_flow" / "position_price_flow_backtest_nav.png",
            ],
        },
    ]


def _collect_strategy_section(report_dir: Path, product: str) -> dict:
    strategy_dir = report_dir / ("ni_vix_panic_reversion" if product == "NI" else "vix_panic_reversion")
    strategy_name = "VIX + 沪镍恐慌反转策略" if product == "NI" else "VIX + 标普500恐慌反转策略"
    return {
        "title": strategy_name,
        "description": FACTOR_EXPLANATIONS["strategy"]["description"],
        "summary": strategy_dir / "latest_summary.md",
        "images": [strategy_dir / "backtest_chart.png"],
    }


def export_pdf_report(product: str, output_dir: Path | None = None) -> Path:
    """生成数据图表 PDF 报告。"""
    product = product.upper()
    report_dir = output_dir or PROCESSED_DATA_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if product == "ALL":
        summary_path = report_dir / "summary" / "latest_factor_summary.md"
        pdf_path = report_dir / "summary" / "chart_report.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        products = ["NI", "SS"]

        with PdfPages(pdf_path) as pdf:
            _render_cover_page(
                pdf,
                "双品种数据图表报告",
                [
                    f"生成时间: {timestamp}",
                    "内容包括目录、多品种总览、摘要与数据图表。",
                    "本报告不再混入因子手册，便于单独打印图表。",
                ],
            )
            _render_toc_page(
                pdf,
                "目录",
                _build_all_products_toc(products),
                subtitle="章节与页码概览",
                footer="完整报告目录",
            )
            _render_product_overview_table(pdf, report_dir / "summary" / "latest_factor_summary.csv")
            for item in products:
                product_base = report_dir / item.lower()
                for section in _collect_product_sections(product_base):
                    _factor_section(
                        pdf,
                        f"{_get_product_name(item)} - {section['title']}",
                        section["description"],
                        section["summary"],
                        section["images"],
                    )
                strategy = _collect_strategy_section(report_dir, item)
                _factor_section(
                    pdf,
                    f"{_get_product_name(item)} - {strategy['title']}",
                    strategy["description"],
                    strategy["summary"],
                    strategy["images"],
                )
        return pdf_path

    base_dir = report_dir / product.lower()
    pdf_path = base_dir / f"{product.lower()}_chart_report.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(pdf_path) as pdf:
        _render_cover_page(
            pdf,
            f"{_get_product_name(product)} 数据图表报告",
            [
                f"生成时间: {timestamp}",
                "内容包括目录、最新摘要和主要图表。",
                "本报告只保留数据图表部分，便于单独打印。",
            ],
        )
        _render_toc_page(
            pdf,
            "目录",
            _build_single_product_toc(product),
            subtitle="章节与页码概览",
            footer=f"{_get_product_name(product)} 报告目录",
        )
        for section in _collect_product_sections(base_dir):
            _factor_section(
                pdf,
                section["title"],
                section["description"],
                section["summary"],
                section["images"],
            )

        strategy = _collect_strategy_section(report_dir, product)
        _factor_section(
            pdf,
            strategy["title"],
            strategy["description"],
            strategy["summary"],
            strategy["images"],
        )

    return pdf_path


def export_factor_manual_pdf(output_dir: Path | None = None) -> Path:
    """生成因子手册 PDF。"""
    report_dir = output_dir or PROCESSED_DATA_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / "factor_manual.pdf"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        _render_cover_page(
            pdf,
            "因子手册",
            [
                f"生成时间: {timestamp}",
                "内容包括因子名称、公式和业务解释。",
                "vv",
            ],
        )
        _render_text_page(
            pdf,
            "手册说明",
            [
                "本手册汇总当前项目里的核心研究因子。",
                "每个因子都包含名称、计算公式和业务解释，便于统一口径。",
                "当前纳入的内容包括：展期收益率、价格动量、MACD、虚实盘比，以及 RSI、VIX 情绪过滤和 VIX + RSI 策略。",
                "公式页使用 LaTeX 风格数学排版，适合直接作为方法说明材料。",
            ],
            subtitle="概览页",
            footer="输出位置: data/processed/factor_manual.pdf",
        )

        total = len(FACTOR_MANUAL_ENTRIES)
        for idx in range(0, total, 2):
            _render_manual_entries_page(pdf, FACTOR_MANUAL_ENTRIES[idx : idx + 2], idx + 1, total)

    return pdf_path

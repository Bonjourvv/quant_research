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


def _wrap_lines(lines: Sequence[str], width: int = 34) -> List[str]:
    wrapped: List[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        chunks = textwrap.wrap(line, width=width) or [line]
        wrapped.extend(chunks)
    return wrapped


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
    fig.patches.append(
        patches.Rectangle(
            (left, bottom),
            width,
            height,
            transform=fig.transFigure,
            facecolor="#f2f7fd",
            edgecolor="#c4d6e8",
            linewidth=1.0,
            zorder=-7,
        )
    )

    img_w, img_h = _get_image_dimensions(image_path)
    box_w = width - 0.04
    box_h = height - 0.09
    scale = min(box_w / img_w, box_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    x = left + (width - draw_w) / 2
    y = bottom + 0.05 + (box_h - draw_h) / 2

    ax = fig.add_axes([x, y, draw_w, draw_h])
    ax.imshow(mpimg.imread(image_path), interpolation="nearest")
    ax.axis("off")

    fig.text(left + 0.02, bottom + height - 0.03, caption, fontsize=10.5, color=TEXT, va="top", fontweight="bold")


def _render_image_gallery_page(
    pdf: PdfPages,
    title: str,
    image_paths: Sequence[Path],
    subtitle: str | None = None,
) -> None:
    images = [path for path in image_paths if path.exists()]
    if not images:
        return

    fig, _ = _new_page()
    _draw_page_shell(fig, title, subtitle)

    if len(images) == 1:
        _draw_single_image_card(fig, images[0], 0.10, 0.16, 0.80, 0.62, images[0].stem.replace("_", " "))
    else:
        top_images = images[:2]
        for idx, image_path in enumerate(top_images):
            left = 0.10 if idx == 0 else 0.52
            _draw_single_image_card(fig, image_path, left, 0.49, 0.34, 0.28, image_path.stem.replace("_", " "))

        remaining = images[2:]
        if remaining:
            if len(remaining) == 1:
                _draw_single_image_card(fig, remaining[0], 0.10, 0.14, 0.76, 0.26, remaining[0].stem.replace("_", " "))
            else:
                for idx, image_path in enumerate(remaining[:2]):
                    left = 0.10 if idx == 0 else 0.52
                    _draw_single_image_card(fig, image_path, left, 0.14, 0.34, 0.26, image_path.stem.replace("_", " "))

    _add_footer(fig, "图表按原始比例居中排版，避免拉伸失真。")
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


def _collect_product_sections(base_dir: Path) -> List[dict]:
    return [
        {
            "title": FACTOR_EXPLANATIONS["roll_yield"]["title"],
            "description": FACTOR_EXPLANATIONS["roll_yield"]["description"],
            "summary": base_dir / "latest_summary.md",
            "images": [
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
            ],
        },
        {
            "title": FACTOR_EXPLANATIONS["virtual_ratio"]["title"],
            "description": FACTOR_EXPLANATIONS["virtual_ratio"]["description"],
            "summary": base_dir / "virtual_ratio" / "latest_summary.md",
            "images": [
                base_dir / "virtual_ratio" / "virtual_real_ratio_rolling_ic.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_group_returns.png",
                base_dir / "virtual_ratio" / "virtual_real_ratio_backtest_nav.png",
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
    """生成研究 PDF 报告。"""
    product = product.upper()
    report_dir = output_dir or PROCESSED_DATA_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if product == "ALL":
        summary_path = report_dir / "summary" / "latest_factor_summary.md"
        pdf_path = report_dir / "summary" / "factor_report.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        with PdfPages(pdf_path) as pdf:
            _render_cover_page(
                pdf,
                "双品种研究报告",
                [
                    f"生成时间: {timestamp}",
                    "内容包括双品种摘要、因子解释与主要图表。",
                    "版式已针对打印阅读优化。",
                ],
            )
            _render_text_page(
                pdf,
                "双品种摘要",
                _read_markdown_lines(summary_path) or ["当前未找到双品种摘要，请先运行 summary 或 all。"],
                footer=f"摘要来源: {summary_path}",
                subtitle="概览页",
            )

            for item in ["NI", "SS"]:
                product_base = report_dir / item.lower()
                _render_text_page(
                    pdf,
                    f"{_get_product_name(item)} 报告说明",
                    [
                        f"品种: {_get_product_name(item)}",
                        "以下页面依次展示该品种的因子解释、最新摘要和图表。",
                    ],
                    subtitle="章节页",
                )
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
    pdf_path = base_dir / f"{product.lower()}_factor_report.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(pdf_path) as pdf:
        _render_cover_page(
            pdf,
            f"{_get_product_name(product)} 研究报告",
            [
                f"生成时间: {timestamp}",
                "内容包括因子解释、最新摘要和主要图表。",
                "版式已针对打印阅读优化。",
            ],
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

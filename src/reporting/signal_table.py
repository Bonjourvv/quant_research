"""导出指标信号总表图片。"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import pandas as pd

from config.settings import PRODUCT_CONFIG, PROCESSED_DATA_DIR
from src.plotting import setup_chinese_font

setup_chinese_font()

PAGE_BG = "#ffffff"
TEXT = "#222222"
GRID = "#d9d9d9"
HEADER_BG = "#f2f2f2"
ALT_BG = "#fbfbfb"

SIGNAL_STYLE = {
    "bullish": ("偏多", "#fde8e8", "#a11d33"),
    "watch_bullish": ("偏多观察", "#fce8ec", "#b4233c"),
    "uptrend": ("上行", "#fdecec", "#a11d33"),
    "strong_uptrend": ("强上行", "#f8d7da", "#8b1e2d"),
    "long_buildup": ("多头增仓", "#fde8e8", "#a11d33"),
    "short_covering": ("空头回补", "#fce8ec", "#b4233c"),
    "bearish": ("偏空", "#dff3e4", "#1b6e3c"),
    "downtrend": ("下行", "#e8f5e9", "#1b6e3c"),
    "strong_downtrend": ("强下行", "#d9f2df", "#155d33"),
    "short_buildup": ("空头增仓", "#dff3e4", "#1b6e3c"),
    "long_unwinding": ("多头离场", "#eaf7ec", "#2d6a3f"),
    "active": ("活跃博弈", "#fff4d6", "#a36a00"),
    "neutral": ("中性", "#f0f0f0", "#555555"),
    "sideways": ("震荡", "#f0f0f0", "#555555"),
}


def _read_summary_kv(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        data[key.strip("- ").strip()] = value.strip()
    return data


def _percentile_text(series: pd.Series, current: float) -> str:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty or pd.isna(current):
        return "--"
    pct = (clean <= current).mean()
    if pct >= 0.9:
        label = "极高"
    elif pct >= 0.7:
        label = "偏高"
    elif pct <= 0.1:
        label = "极低"
    elif pct <= 0.3:
        label = "偏低"
    else:
        label = "中性"
    return f"{pct*100:.1f}%分位（{label}）"


def _signal_badge(signal: str, fallback: str = "neutral") -> Tuple[str, str, str]:
    key = str(signal or fallback)
    return SIGNAL_STYLE.get(key, SIGNAL_STYLE.get(fallback, SIGNAL_STYLE["neutral"]))


def _threshold_hit_text(hit: bool, reason: str) -> str:
    return f"是 | {reason}" if hit else f"否 | {reason}"


def _load_rows_for_product(product_code: str) -> List[Dict[str, str]]:
    product_name = PRODUCT_CONFIG[product_code]["name"]
    base_dir = PROCESSED_DATA_DIR / product_code.lower()
    rows: List[Dict[str, str]] = []

    roll_df = pd.read_csv(PROCESSED_DATA_DIR / f"{product_code.lower()}_roll_yield_weighted_avg.csv", parse_dates=["trade_date"])
    roll_latest = roll_df.dropna(subset=["roll_yield"]).iloc[-1]
    roll_q10 = roll_df["roll_yield"].quantile(0.10)
    roll_q90 = roll_df["roll_yield"].quantile(0.90)
    roll_hit = roll_latest["roll_yield"] <= roll_q10 or roll_latest["roll_yield"] >= roll_q90
    roll_signal = "bullish" if roll_latest["roll_yield"] <= roll_q10 else "bearish" if roll_latest["roll_yield"] >= roll_q90 else "neutral"
    rows.append(
        {
            "品种": product_name,
            "指标": "展期收益率",
            "当前数据": f"{roll_latest['roll_yield']*100:+.2f}%",
            "历史位置": _percentile_text(roll_df["roll_yield"], roll_latest["roll_yield"]),
            "是否触及阈值": _threshold_hit_text(roll_hit, f"10%={roll_q10*100:+.2f}% / 90%={roll_q90*100:+.2f}%"),
            "指向": roll_signal,
        }
    )

    mom_df = pd.read_csv(base_dir / "momentum" / "momentum_signals.csv", parse_dates=["trade_date"])
    mom_latest = mom_df.dropna(subset=["momentum_return"]).iloc[-1]
    mom_q10 = mom_df["momentum_return"].quantile(0.10)
    mom_q90 = mom_df["momentum_return"].quantile(0.90)
    mom_hit = mom_latest["momentum_return"] <= mom_q10 or mom_latest["momentum_return"] >= mom_q90
    mom_signal = "bullish" if int(mom_latest["signal"]) > 0 else "bearish" if int(mom_latest["signal"]) < 0 else mom_latest["trend_label"]
    rows.append(
        {
            "品种": product_name,
            "指标": "价格动量",
            "当前数据": f"20日动量 {mom_latest['momentum_return']*100:+.2f}% | 趋势强度 {mom_latest['trend_strength']*100:+.2f}%",
            "历史位置": _percentile_text(mom_df["momentum_return"], mom_latest["momentum_return"]),
            "是否触及阈值": _threshold_hit_text(mom_hit, f"10%={mom_q10*100:+.2f}% / 90%={mom_q90*100:+.2f}%"),
            "指向": mom_signal,
        }
    )

    macd_df = pd.read_csv(base_dir / "macd" / "macd_signals.csv", parse_dates=["trade_date"])
    macd_latest = macd_df.dropna(subset=["macd_hist"]).iloc[-1]
    macd_hit = int(macd_latest["signal"]) != 0
    macd_signal = "bullish" if int(macd_latest["position"]) > 0 else "bearish" if int(macd_latest["position"]) < 0 else macd_latest["trend"]
    rows.append(
        {
            "品种": product_name,
            "指标": "MACD",
            "当前数据": f"柱 {macd_latest['macd_hist']:+.2f} | DIF/DEA {macd_latest['dif']:.1f}/{macd_latest['dea']:.1f}",
            "历史位置": _percentile_text(macd_df["macd_hist"], macd_latest["macd_hist"]),
            "是否触及阈值": _threshold_hit_text(macd_hit, "金叉/死叉触发" if macd_hit else "未出现金叉死叉"),
            "指向": macd_signal,
        }
    )

    vr_df = pd.read_csv(base_dir / "virtual_ratio" / "virtual_ratio_signals.csv", parse_dates=["trade_date"])
    vr_latest = vr_df.dropna(subset=["virtual_real_ratio"]).iloc[-1]
    vr_q25 = vr_df["virtual_real_ratio"].quantile(0.25)
    vr_q75 = vr_df["virtual_real_ratio"].quantile(0.75)
    vr_hit = vr_latest["virtual_real_ratio"] <= vr_q25 or vr_latest["virtual_real_ratio"] >= vr_q75 or str(vr_latest["signal"]) != "neutral"
    rows.append(
        {
            "品种": product_name,
            "指标": "虚实盘比",
            "当前数据": f"{vr_latest['virtual_real_ratio']:.3f} | 持仓变化 {vr_latest['oi_change']:+.0f}",
            "历史位置": _percentile_text(vr_df["virtual_real_ratio"], vr_latest["virtual_real_ratio"]),
            "是否触及阈值": _threshold_hit_text(vr_hit, f"25%={vr_q25:.3f} / 75%={vr_q75:.3f}"),
            "指向": str(vr_latest["signal"]),
        }
    )

    skew_df = pd.read_csv(base_dir / "intraday_skew" / "intraday_skew_signals.csv", parse_dates=["trade_date"])
    skew_latest = skew_df.dropna(subset=["skew_factor"]).iloc[-1]
    skew_q10 = skew_df["skew_factor"].quantile(0.10)
    skew_q90 = skew_df["skew_factor"].quantile(0.90)
    skew_hit = skew_latest["skew_factor"] <= skew_q10 or skew_latest["skew_factor"] >= skew_q90
    skew_signal = "bullish" if skew_latest["skew_factor"] <= skew_q10 else "bearish" if skew_latest["skew_factor"] >= skew_q90 else "neutral"
    rows.append(
        {
            "品种": product_name,
            "指标": "5分钟偏度",
            "当前数据": f"{skew_latest['skew_factor']:+.4f} | 上/下偏 {skew_latest['upside_skew']:+.2f}/{skew_latest['downside_skew']:+.2f}",
            "历史位置": _percentile_text(skew_df["skew_factor"], skew_latest["skew_factor"]),
            "是否触及阈值": _threshold_hit_text(skew_hit, f"10%={skew_q10:+.4f} / 90%={skew_q90:+.4f}"),
            "指向": skew_signal,
        }
    )

    combo_df = pd.read_csv(base_dir / "roll_virtual_combo" / "roll_virtual_combo_signals.csv", parse_dates=["trade_date"])
    combo_latest = combo_df.dropna(subset=["combo_score"]).iloc[-1]
    combo_q10 = combo_df["combo_score"].quantile(0.10)
    combo_q90 = combo_df["combo_score"].quantile(0.90)
    combo_hit = combo_latest["combo_score"] <= combo_q10 or combo_latest["combo_score"] >= combo_q90 or str(combo_latest["signal"]) != "neutral"
    rows.append(
        {
            "品种": product_name,
            "指标": "展期+虚实盘组合",
            "当前数据": f"组合得分 {combo_latest['combo_score']:+.2f} | 共振 {combo_latest['agreement_boost']:.2f}",
            "历史位置": _percentile_text(combo_df["combo_score"], combo_latest["combo_score"]),
            "是否触及阈值": _threshold_hit_text(combo_hit, f"10%={combo_q10:+.2f} / 90%={combo_q90:+.2f}"),
            "指向": str(combo_latest["signal"]),
        }
    )

    flow_df = pd.read_csv(base_dir / "position_flow" / "position_flow_signals.csv", parse_dates=["trade_date"])
    flow_latest = flow_df.dropna(subset=["position_flow_factor"]).iloc[-1]
    flow_hit = str(flow_latest["signal"]) != "neutral"
    rows.append(
        {
            "品种": product_name,
            "指标": "持仓-价格联动",
            "当前数据": f"涨跌 {flow_latest['price_change']*100:+.2f}% | 持仓变化 {flow_latest['oi_change_pct']*100:+.2f}%",
            "历史位置": _percentile_text(flow_df["position_flow_factor"], flow_latest["position_flow_factor"]),
            "是否触及阈值": _threshold_hit_text(flow_hit, "结构型阈值" if flow_hit else "未触发结构型阈值"),
            "指向": str(flow_latest["signal"]),
        }
    )

    return rows


def _draw_wrapped_text(ax, x0: float, y0: float, width: float, text: str, fontsize: float, color: str = TEXT, weight: str = "normal") -> None:
    char_width = max(10, int(width * 95))
    wrapped = textwrap.fill(str(text), width=char_width, break_long_words=False, break_on_hyphens=False)
    ax.text(x0 + 0.006, y0, wrapped, ha="left", va="center", fontsize=fontsize, color=color, fontweight=weight)


def export_signal_table_image(product: str = "ALL", output_dir: Path | None = None) -> Path:
    """导出指标信号总表 PNG。"""
    report_dir = output_dir or PROCESSED_DATA_DIR
    summary_dir = report_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    product = (product or "ALL").upper()
    product_codes = ["NI", "SS", "CU"] if product == "ALL" else [product]

    rows: List[Dict[str, str]] = []
    for code in product_codes:
        rows.extend(_load_rows_for_product(code))

    df = pd.DataFrame(rows)
    output_path = summary_dir / "indicator_signal_table.png"

    n_rows = len(df)
    fig_h = max(8, 1.0 + (n_rows + 1) * 0.5)
    fig, ax = plt.subplots(figsize=(18, fig_h))
    fig.patch.set_facecolor(PAGE_BG)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    title = f"全指标交易信号总表  |  生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ax.text(0.02, 0.97, title, fontsize=20, fontweight="bold", color=TEXT, va="top")

    columns = ["品种", "指标", "当前数据", "当前数据在历史数据的位置", "指向（交易提示）", "是否触及阈值"]
    widths = [0.07, 0.14, 0.24, 0.16, 0.14, 0.21]
    x_positions = [0.02]
    for w in widths[:-1]:
        x_positions.append(x_positions[-1] + w)

    top = 0.91
    row_h = 0.82 / (n_rows + 1)

    # header
    y = top - row_h
    for x, w, col in zip(x_positions, widths, columns):
        ax.add_patch(patches.Rectangle((x, y), w, row_h, facecolor=HEADER_BG, edgecolor=GRID, linewidth=1.0))
        _draw_wrapped_text(ax, x, y + row_h / 2, w, col, fontsize=12.5, weight="bold")

    for idx, row in df.iterrows():
        y = top - (idx + 2) * row_h
        bg = "#ffffff" if idx % 2 == 0 else ALT_BG
        display_signal, fill_color, text_color = _signal_badge(row["指向"])
        values = [
            row["品种"],
            row["指标"],
            row["当前数据"],
            row["历史位置"],
            display_signal,
            row["是否触及阈值"],
        ]
        for col_idx, (x, w, value) in enumerate(zip(x_positions, widths, values)):
            face = fill_color if col_idx == 4 else bg
            ax.add_patch(patches.Rectangle((x, y), w, row_h, facecolor=face, edgecolor=GRID, linewidth=0.9))
            color = text_color if col_idx == 4 else TEXT
            weight = "bold" if col_idx == 4 else "normal"
            _draw_wrapped_text(ax, x, y + row_h / 2, w, value, fontsize=11.0, color=color, weight=weight)

    footer = (
        "说明：历史位置按当前值在该指标历史样本中的分位计算；“是否触及阈值”使用当前系统的分位阈值或结构触发规则；"
        "交易指向颜色：绿色偏多，红色偏空，灰色中性，橙色表示活跃或离场。"
    )
    ax.text(0.02, 0.03, textwrap.fill(footer, width=120), fontsize=10.5, color="#555555", va="bottom")

    fig.tight_layout()
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return output_path

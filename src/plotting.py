"""绘图公共配置。"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.dates import DateFormatter, MonthLocator


def setup_chinese_font() -> None:
    """配置 matplotlib 中文字体，避免中文标题乱码。"""
    candidates = [
        "Hiragino Sans GB",
        "PingFang SC",
        "Songti SC",
        "STHeiti",
        "Arial Unicode MS",
        "SimHei",
        "Noto Sans CJK SC",
    ]

    available = set()
    for font in font_manager.fontManager.ttflist:
        available.add(font.name)

    for family in candidates:
        if family in available:
            plt.rcParams["font.sans-serif"] = [family] + list(plt.rcParams.get("font.sans-serif", []))
            plt.rcParams["axes.unicode_minus"] = False
            return


SEASONAL_COLOR_MAP = {
    2022: "#000000",
    2023: "#70AD47",
    2024: "#5B9BD5",
    2025: "#FFC000",
    2026: "#C00000",
}

EXPORT_DPI = 320


def plot_seasonal_chart(
    data: pd.DataFrame,
    value_col: str,
    output_path: str | Path,
    title: str,
    y_label: str,
    date_col: str = "trade_date",
) -> str:
    """绘制 2022-2026 年度叠加季节图。"""
    df = data.copy()
    if df.empty:
        return str(output_path)

    df[date_col] = pd.to_datetime(df[date_col])
    df = df[[date_col, value_col]].dropna().copy()
    if df.empty:
        return str(output_path)

    df["year"] = df[date_col].dt.year
    df = df[df["year"].between(2022, 2026)].copy()
    if df.empty:
        return str(output_path)

    df["season_date"] = pd.to_datetime(
        "2000-" + df[date_col].dt.strftime("%m-%d"),
        format="%Y-%m-%d",
        errors="coerce",
    )
    df = df.dropna(subset=["season_date"]).sort_values(["year", "season_date"])
    if df.empty:
        return str(output_path)

    fig, ax = plt.subplots(figsize=(12, 5))
    for year, color in SEASONAL_COLOR_MAP.items():
        subset = df[df["year"] == year]
        if subset.empty:
            continue
        ax.plot(
            subset["season_date"],
            subset[value_col],
            label=str(year),
            color=color,
            linewidth=1.8,
        )

    ax.set_title(title)
    ax.set_ylabel(y_label)
    ax.set_xlabel("季节位置（月-日）")
    ax.xaxis.set_major_locator(MonthLocator())
    ax.xaxis.set_major_formatter(DateFormatter("%m-%d"))
    ax.grid(alpha=0.2)
    ax.legend(ncol=min(5, len(df["year"].unique())), frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=EXPORT_DPI)
    plt.close(fig)
    return str(output_path)

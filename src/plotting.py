"""绘图公共配置。"""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib import font_manager


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

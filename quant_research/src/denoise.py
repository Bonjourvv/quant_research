"""因子分析中的轻量降噪工具。"""

from __future__ import annotations

import pandas as pd


def winsorize_series(series: pd.Series, quantile: float = 0.01) -> pd.Series:
    """按分位数截尾，抑制极端值对因子分布的扭曲。"""
    if series is None or series.dropna().empty or quantile <= 0:
        return series

    lower = series.quantile(quantile)
    upper = series.quantile(1 - quantile)
    return series.clip(lower=lower, upper=upper)


def rolling_median_series(series: pd.Series, window: int = 3) -> pd.Series:
    """滚动中位数，比均值更稳健，适合去掉单日毛刺。"""
    if series is None or window <= 1:
        return series
    return series.rolling(window=window, min_periods=1).median()


def add_switch_noise_flag(df: pd.DataFrame, code_col: str = "dominant_code") -> pd.DataFrame:
    """标记主力切换当天及次日，便于对连续价格因子做保护。"""
    output = df.copy()
    switched = output[code_col].ne(output[code_col].shift(1)).fillna(False)
    if not output.empty:
        switched.iloc[0] = False
    output["dominant_switch"] = switched
    output["switch_noise"] = switched | switched.shift(1, fill_value=False)
    return output

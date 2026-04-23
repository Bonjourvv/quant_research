"""
展期收益率 + 虚实盘比 组合因子。

思路：
- 展期收益率越低（更深贴水）通常越偏多
- 虚实盘比越低（换手更沉淀）通常越偏多
- 当两个因子方向一致时，提高组合信号权重
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


class RollVirtualComboFactor:
    """展期收益率与虚实盘比的组合因子。"""

    def __init__(
        self,
        roll_weight: float = 0.6,
        ratio_weight: float = 0.4,
        z_window: int = 120,
        min_periods: int = 30,
    ) -> None:
        self.roll_weight = roll_weight
        self.ratio_weight = ratio_weight
        self.z_window = z_window
        self.min_periods = min_periods

    def _rolling_zscore(self, series: pd.Series) -> pd.Series:
        rolling_mean = series.rolling(self.z_window, min_periods=self.min_periods).mean()
        rolling_std = series.rolling(self.z_window, min_periods=self.min_periods).std()
        zscore = (series - rolling_mean) / rolling_std.replace(0, np.nan)
        return zscore.clip(-3, 3)

    def calc_factor_values(
        self,
        roll_yield_data: pd.DataFrame,
        virtual_ratio_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """合成历史组合因子序列。"""
        roll_df = roll_yield_data[["trade_date", "roll_yield"]].copy()
        ratio_df = virtual_ratio_data[
            ["trade_date", "dominant_code", "close", "virtual_real_ratio", "oi_change", "vol_change", "signal", "signal_text"]
        ].copy()

        roll_df["trade_date"] = pd.to_datetime(roll_df["trade_date"])
        ratio_df["trade_date"] = pd.to_datetime(ratio_df["trade_date"])

        df = pd.merge(roll_df, ratio_df, on="trade_date", how="inner")
        df = df.sort_values("trade_date").reset_index(drop=True)

        df["roll_component"] = -self._rolling_zscore(df["roll_yield"])
        df["ratio_component"] = -self._rolling_zscore(df["virtual_real_ratio"])

        aligned = np.sign(df["roll_component"].fillna(0)) == np.sign(df["ratio_component"].fillna(0))
        df["agreement_boost"] = np.where(aligned, 1.15, 0.85)
        df["combo_score_raw"] = (
            self.roll_weight * df["roll_component"] + self.ratio_weight * df["ratio_component"]
        )
        df["combo_score"] = df["combo_score_raw"] * df["agreement_boost"]
        df["combo_score"] = df["combo_score"].clip(-5, 5)

        upper = df["combo_score"].rolling(self.z_window, min_periods=self.min_periods).quantile(0.9)
        lower = df["combo_score"].rolling(self.z_window, min_periods=self.min_periods).quantile(0.1)

        df["signal"] = "neutral"
        df["signal_text"] = "展期与虚实盘信号未形成共振，维持中性判断"
        df.loc[df["combo_score"] >= upper, "signal"] = "bullish"
        df.loc[df["combo_score"] >= upper, "signal_text"] = "贴水与低虚实盘比共振，偏多信号增强"
        df.loc[df["combo_score"] <= lower, "signal"] = "bearish"
        df.loc[df["combo_score"] <= lower, "signal_text"] = "升水与高虚实盘比共振，偏空信号增强"

        return df

    def summarize_latest(self, factor_data: pd.DataFrame) -> Dict[str, object]:
        latest = factor_data.dropna(subset=["combo_score"]).iloc[-1]
        return latest.to_dict()

    def print_analysis_report(self, factor_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
        latest = self.summarize_latest(factor_data)

        print("\n" + "=" * 80)
        print("  展期收益率 + 虚实盘比组合因子分析")
        print("=" * 80)
        print("\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  主力合约: {latest['dominant_code']}")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  展期收益率: {latest['roll_yield']*100:+.2f}%")
        print(f"  虚实盘比: {latest['virtual_real_ratio']:.3f}")
        print(f"  展期分量: {latest['roll_component']:+.2f}")
        print(f"  虚实盘比分量: {latest['ratio_component']:+.2f}")
        print(f"  共振系数: {latest['agreement_boost']:.2f}")
        print(f"  组合得分: {latest['combo_score']:+.2f}")
        print(f"  交易信号: {latest['signal']}")
        print(f"  信号解读: {latest['signal_text']}")

        print("\n【历史统计】")
        print(f"  样本数量: {factor_data['combo_score'].notna().sum()}")
        print(f"  组合得分均值: {factor_data['combo_score'].mean():+.3f}")
        print(f"  组合得分标准差: {factor_data['combo_score'].std():.3f}")
        print(f"  做多信号占比: {(factor_data['signal'] == 'bullish').mean()*100:.1f}%")
        print(f"  做空信号占比: {(factor_data['signal'] == 'bearish').mean()*100:.1f}%")
        print("=" * 80 + "\n")

        return factor_data, latest

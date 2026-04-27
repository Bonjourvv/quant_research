"""
价格动量因子模块。

定义：
- 原始动量：过去 N 日收益率
- 趋势强度：短期均线相对长期均线的偏离
- 趋势状态：上涨 / 下跌 / 震荡
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class MomentumFactor:
    """价格动量因子计算器。"""

    def __init__(
        self,
        lookback_days: int = 20,
        short_window: int = 10,
        long_window: int = 60,
    ):
        self.lookback_days = lookback_days
        self.short_window = short_window
        self.long_window = long_window

    def calc_momentum(self, price_data: pd.DataFrame) -> pd.DataFrame:
        """计算动量因子及趋势状态。"""
        df = price_data.copy()
        df = df.sort_values("trade_date").reset_index(drop=True)

        df["momentum_return"] = df["close"] / df["close"].shift(self.lookback_days) - 1
        df["ma_short"] = df["close"].rolling(self.short_window, min_periods=self.short_window).mean()
        df["ma_long"] = df["close"].rolling(self.long_window, min_periods=self.long_window).mean()
        df["trend_strength"] = df["ma_short"] / df["ma_long"] - 1

        vol = df["close"].pct_change().rolling(self.lookback_days, min_periods=max(5, self.lookback_days // 2)).std()
        df["momentum_zscore"] = df["momentum_return"] / vol.replace(0, np.nan)

        df["trend_label"] = "sideways"
        bullish = (df["momentum_return"] > 0) & (df["trend_strength"] > 0)
        bearish = (df["momentum_return"] < 0) & (df["trend_strength"] < 0)
        df.loc[bullish, "trend_label"] = "uptrend"
        df.loc[bearish, "trend_label"] = "downtrend"

        return df

    def generate_signals(self, momentum_data: pd.DataFrame) -> pd.DataFrame:
        """根据信号阈值生成持仓。"""
        df = momentum_data.copy()

        df["signal"] = 0
        df.loc[df["trend_label"] == "uptrend", "signal"] = 1
        df.loc[df["trend_label"] == "downtrend", "signal"] = -1

        df["position"] = df["signal"].replace(0, np.nan).ffill().fillna(0)
        return df

    def summarize_latest(self, signal_data: pd.DataFrame) -> Dict:
        """汇总最新状态。"""
        latest = signal_data.dropna(subset=["momentum_return"]).iloc[-1]

        return {
            "trade_date": latest["trade_date"],
            "close": latest["close"],
            "momentum_return": latest["momentum_return"],
            "trend_strength": latest["trend_strength"],
            "momentum_zscore": latest["momentum_zscore"],
            "trend_label": latest["trend_label"],
            "signal": int(latest["signal"]),
        }

    def print_analysis_report(self, price_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """打印动量分析摘要。"""
        momentum_data = self.calc_momentum(price_data)
        signal_data = self.generate_signals(momentum_data)
        latest = self.summarize_latest(signal_data)

        print("\n" + "=" * 80)
        print(f"  价格动量因子分析 (lookback={self.lookback_days}, MA={self.short_window}/{self.long_window})")
        print("=" * 80)
        print(f"\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  {self.lookback_days}日动量: {latest['momentum_return']*100:+.2f}%")
        print(f"  趋势强度: {latest['trend_strength']*100:+.2f}%")
        print(f"  动量Z分数: {latest['momentum_zscore']:+.2f}")
        print(f"  趋势标签: {latest['trend_label']}")
        print(f"  交易信号: {latest['signal']:+d}")
        print(f"\n【分布统计】")
        print(f"  样本数量: {signal_data['momentum_return'].notna().sum()}")
        print(f"  动量均值: {signal_data['momentum_return'].mean()*100:+.2f}%")
        print(f"  动量标准差: {signal_data['momentum_return'].std()*100:+.2f}%")
        print(f"  上涨趋势占比: {(signal_data['trend_label'] == 'uptrend').mean()*100:.1f}%")
        print(f"  下跌趋势占比: {(signal_data['trend_label'] == 'downtrend').mean()*100:.1f}%")
        print(f"  震荡占比: {(signal_data['trend_label'] == 'sideways').mean()*100:.1f}%")
        print("=" * 80 + "\n")

        return signal_data, latest


def main() -> None:
    """单文件运行入口，只使用真实历史数据。"""
    parser = argparse.ArgumentParser(description="价格动量因子测试")
    parser.add_argument("--product", default="NI", help="品种代码，默认 NI")
    args = parser.parse_args()
    product = args.product.upper()

    print("=" * 60)
    print(f"{product} 价格动量因子测试")
    print("=" * 60)

    cache_file = os.path.join(PROJECT_ROOT, "data", "processed", f"{product.lower()}_contracts_daily.csv")
    if not os.path.exists(cache_file):
        raise FileNotFoundError(
            f"未找到真实历史数据: {cache_file}。"
            f"请先运行 `python run_factors.py history --product {product}` 生成缓存后，再执行动量分析。"
        )

    from src.factors.macd import load_dominant_price

    print(f"\n从缓存加载数据: {cache_file}")
    contracts_data = pd.read_csv(cache_file, dtype={"trade_date": str})
    price_data = load_dominant_price(contracts_data)
    print(f"主力合约价格数据: {len(price_data)} 条")

    momentum = MomentumFactor()
    momentum.print_analysis_report(price_data)


if __name__ == "__main__":
    main()

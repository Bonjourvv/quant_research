"""
基于 5 分钟收益率的日内偏度因子。

定义：
    skew_t = E[((ret_i - mu) / sigma)^3]

扩展：
- upside_skew: 仅统计正收益子样本的偏度
- downside_skew: 仅统计负收益子样本的偏度
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

from src.data_fetcher.ths_client import THSClient


def load_dominant_contract_by_date(contracts_data: pd.DataFrame) -> pd.DataFrame:
    """提取每日主力合约及对应收盘价。"""
    df = contracts_data.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
    idx = df.groupby("trade_date")["oi"].idxmax()
    dominant = df.loc[idx, ["trade_date", "ts_code", "close", "oi"]].copy()
    dominant.columns = ["trade_date", "dominant_code", "close", "oi"]
    return dominant.sort_values("trade_date").reset_index(drop=True)


@dataclass
class IntradaySkewConfig:
    period: int = 5
    lookback_days: int = 120
    min_bars: int = 24


class IntradaySkewFactor:
    """基于主力合约 5 分钟收益率的偏度因子。"""

    def __init__(self, ths_client: Optional[THSClient] = None, config: Optional[IntradaySkewConfig] = None) -> None:
        self.ths_client = ths_client or THSClient()
        self.config = config or IntradaySkewConfig()

    @staticmethod
    def _calc_standardized_skew(returns: pd.Series) -> float:
        valid = returns.dropna()
        if len(valid) < 3:
            return np.nan
        mu = valid.mean()
        sigma = valid.std(ddof=0)
        if sigma == 0 or np.isnan(sigma):
            return np.nan
        standardized = (valid - mu) / sigma
        return float(np.mean(np.power(standardized, 3)))

    def _calc_daily_skew(self, minute_df: pd.DataFrame) -> Dict[str, float]:
        df = minute_df.copy()
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("time").reset_index(drop=True)
        df["ret_5min"] = df["close"].pct_change()
        returns = df["ret_5min"].dropna()

        if len(returns) < self.config.min_bars:
            return {
                "skew_factor": np.nan,
                "upside_skew": np.nan,
                "downside_skew": np.nan,
                "ret_5min_mean": np.nan,
                "ret_5min_std": np.nan,
                "bar_count": len(df),
            }

        positive = returns[returns > 0]
        negative = returns[returns < 0]
        return {
            "skew_factor": self._calc_standardized_skew(returns),
            "upside_skew": self._calc_standardized_skew(positive),
            "downside_skew": self._calc_standardized_skew(negative),
            "ret_5min_mean": float(returns.mean()),
            "ret_5min_std": float(returns.std(ddof=0)),
            "bar_count": int(len(df)),
        }

    def _fetch_intraday_bars(self, contract_code: str, trade_date: pd.Timestamp) -> pd.DataFrame:
        start_time = f"{trade_date.strftime('%Y-%m-%d')} 09:00:00"
        end_time = f"{trade_date.strftime('%Y-%m-%d')} 15:15:00"
        rows = self.ths_client.get_high_frequency(contract_code, start_time, end_time, period=self.config.period)
        return pd.DataFrame(rows)

    def build_factor_series(
        self,
        dominant_data: pd.DataFrame,
        cache_file: Optional[Path] = None,
    ) -> pd.DataFrame:
        """构建最近若干交易日的偏度因子序列，并支持增量缓存。"""
        working = dominant_data.copy().sort_values("trade_date").reset_index(drop=True)
        if self.config.lookback_days > 0:
            working = working.tail(self.config.lookback_days).reset_index(drop=True)

        existing = pd.DataFrame()
        if cache_file and cache_file.exists():
            existing = pd.read_csv(cache_file, parse_dates=["trade_date"])

        done_dates = set()
        if not existing.empty:
            done_dates = set(existing["trade_date"].dt.normalize())

        rows = []
        for _, row in working.iterrows():
            trade_date = pd.to_datetime(row["trade_date"]).normalize()
            if trade_date in done_dates:
                continue

            minute_df = self._fetch_intraday_bars(row["dominant_code"], trade_date)
            metrics = self._calc_daily_skew(minute_df) if not minute_df.empty else {
                "skew_factor": np.nan,
                "upside_skew": np.nan,
                "downside_skew": np.nan,
                "ret_5min_mean": np.nan,
                "ret_5min_std": np.nan,
                "bar_count": 0,
            }
            rows.append(
                {
                    "trade_date": trade_date,
                    "dominant_code": row["dominant_code"],
                    "close": row["close"],
                    **metrics,
                }
            )

        new_df = pd.DataFrame(rows)
        combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
        if combined.empty:
            combined = working[["trade_date", "dominant_code", "close"]].copy()

        combined["trade_date"] = pd.to_datetime(combined["trade_date"])
        combined = combined.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last").reset_index(drop=True)

        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            combined.to_csv(cache_file, index=False)

        return combined

    def print_analysis_report(self, factor_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
        latest = factor_data.dropna(subset=["skew_factor"]).iloc[-1]

        print("\n" + "=" * 80)
        print("  5分钟收益率偏度因子分析")
        print("=" * 80)
        print("\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  主力合约: {latest['dominant_code']}")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  偏度因子: {latest['skew_factor']:+.4f}")
        print(f"  上行偏度: {latest['upside_skew']:+.4f}")
        print(f"  下行偏度: {latest['downside_skew']:+.4f}")
        print(f"  5分钟收益均值: {latest['ret_5min_mean']*100:+.4f}%")
        print(f"  5分钟收益波动: {latest['ret_5min_std']*100:.4f}%")
        print(f"  分钟K线数量: {int(latest['bar_count'])}")

        signal = "neutral"
        signal_text = "偏度处于中性区域，情绪不对称性不明显"
        p10 = factor_data["skew_factor"].quantile(0.1)
        p90 = factor_data["skew_factor"].quantile(0.9)
        if latest["skew_factor"] <= p10:
            signal = "bullish"
            signal_text = "偏度显著偏低，更像恐慌后超跌状态，偏向均值回归做多"
        elif latest["skew_factor"] >= p90:
            signal = "bearish"
            signal_text = "偏度显著偏高，更像冲高后的拥挤状态，偏向均值回归做空"
        print(f"  交易信号: {signal}")
        print(f"  信号解读: {signal_text}")

        print("\n【历史统计】")
        print(f"  样本数量: {factor_data['skew_factor'].notna().sum()}")
        print(f"  偏度均值: {factor_data['skew_factor'].mean():+.4f}")
        print(f"  偏度标准差: {factor_data['skew_factor'].std():.4f}")
        print(f"  10%分位: {p10:+.4f}")
        print(f"  90%分位: {p90:+.4f}")
        print("=" * 80 + "\n")

        latest_dict = latest.to_dict()
        latest_dict["signal"] = signal
        latest_dict["signal_text"] = signal_text
        return factor_data, latest_dict

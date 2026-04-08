"""
虚实盘比因子模块。

定义：
- 虚实盘比 = 成交量 / 持仓量

直观理解：
- 比值高：换手快，短线交易更活跃
- 比值低：筹码相对沉淀，持仓更稳定

该模块支持：
- 基于主力合约日线的历史因子序列
- 基于同花顺实时行情的实时快照分析
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def load_dominant_contract_features(contracts_data: pd.DataFrame) -> pd.DataFrame:
    """从全合约数据中提取每日主力合约的价格、成交量、持仓量。"""
    df = contracts_data.copy()
    df["trade_date"] = df["trade_date"].astype(str)

    idx = df.groupby("trade_date")["oi"].idxmax()
    dominant = df.loc[idx, ["trade_date", "ts_code", "close", "oi", "vol"]].copy()
    dominant.columns = ["trade_date", "dominant_code", "close", "oi", "vol"]
    dominant["trade_date"] = pd.to_datetime(dominant["trade_date"])
    dominant = dominant.sort_values("trade_date").reset_index(drop=True)
    return dominant


class VirtualRealRatioFactor:
    """虚实盘比因子。"""

    def __init__(self, ths_client=None):
        self.ths_client = ths_client

    def _get_ths_client(self):
        if self.ths_client is None:
            from src.data_fetcher.ths_client import THSClient

            self.ths_client = THSClient()
        return self.ths_client

    def calc_factor_values(self, dominant_data: pd.DataFrame) -> pd.DataFrame:
        """计算历史虚实盘比因子。"""
        df = dominant_data.copy().sort_values("trade_date").reset_index(drop=True)
        df["virtual_real_ratio"] = df["vol"] / df["oi"].replace(0, np.nan)
        df["oi_change"] = df["oi"].diff()
        df["vol_change"] = df["vol"].diff()
        df["oi_change_pct"] = df["oi"].pct_change()
        df["vol_change_pct"] = df["vol"].pct_change()
        df["ratio_zscore"] = (
            (df["virtual_real_ratio"] - df["virtual_real_ratio"].rolling(60, min_periods=20).mean())
            / df["virtual_real_ratio"].rolling(60, min_periods=20).std()
        )
        df = self.generate_signals(df)
        return df

    def generate_signals(self, factor_data: pd.DataFrame) -> pd.DataFrame:
        """生成统一风格的虚实盘比信号。"""
        df = factor_data.copy()
        ratio = df["virtual_real_ratio"]
        oi_change = df["oi_change"]
        zscore = df["ratio_zscore"]

        df["signal"] = "neutral"
        df["signal_text"] = "虚实盘比平稳，短线与持仓结构均衡"

        bullish_mask = (ratio <= ratio.rolling(120, min_periods=30).quantile(0.25)) & (oi_change > 0)
        bearish_mask = (ratio >= ratio.rolling(120, min_periods=30).quantile(0.75)) & (oi_change < 0)
        active_mask = (zscore >= 1.0) & (~bearish_mask)

        df.loc[bullish_mask, "signal"] = "bullish"
        df.loc[bullish_mask, "signal_text"] = "低虚实盘比且增仓，偏向主力沉淀建仓"

        df.loc[bearish_mask, "signal"] = "bearish"
        df.loc[bearish_mask, "signal_text"] = "高虚实盘比且减仓，偏向短线资金离场"

        df.loc[active_mask, "signal"] = "active"
        df.loc[active_mask, "signal_text"] = "虚实盘比显著抬升，短线博弈活跃"
        return df

    def fetch_realtime_snapshot(self, contract_code: str) -> Dict:
        """获取单个合约的实时虚实盘比快照。"""
        client = self._get_ths_client()
        quote = client.get_realtime_quote(contract_code)
        if not quote:
            raise ValueError(f"未获取到实时行情: {contract_code}")

        open_interest = float(quote.get("openInterest", 0))
        volume = float(quote.get("volume", 0))
        latest = float(quote.get("latest", 0))

        return {
            "contract_code": contract_code,
            "latest": latest,
            "volume": volume,
            "open_interest": open_interest,
            "virtual_real_ratio": volume / open_interest if open_interest > 0 else np.nan,
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def interpret_snapshot(self, snapshot: Dict, previous_snapshot: Optional[Dict] = None) -> Dict:
        """对实时快照做业务解读。"""
        ratio = snapshot["virtual_real_ratio"]
        oi_change = np.nan
        vol_change = np.nan

        if previous_snapshot is not None:
            oi_change = snapshot["open_interest"] - previous_snapshot.get("open_interest", 0)
            vol_change = snapshot["volume"] - previous_snapshot.get("volume", 0)

        if pd.isna(ratio):
            status = "无有效持仓量"
            signal = "neutral"
        elif not pd.isna(oi_change) and oi_change > 0 and ratio < 0.30:
            status = "增仓沉淀，主力建仓特征更明显"
            signal = "bullish"
        elif not pd.isna(oi_change) and oi_change > 0 and ratio >= 0.30:
            status = "放量增仓，交易活跃，趋势可能启动"
            signal = "watch_bullish"
        elif not pd.isna(oi_change) and oi_change < 0 and ratio >= 0.30:
            status = "放量减仓，短线博弈后资金离场"
            signal = "bearish"
        elif ratio >= 0.50:
            status = "高换手，短线资金博弈偏强"
            signal = "active"
        else:
            status = "换手和持仓均偏平稳"
            signal = "neutral"

        result = snapshot.copy()
        result["oi_change"] = oi_change
        result["vol_change"] = vol_change
        result["status"] = status
        result["signal"] = signal
        return result

    def print_analysis_report(self, dominant_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """打印历史因子摘要。"""
        factor_data = self.calc_factor_values(dominant_data)
        latest = factor_data.dropna(subset=["virtual_real_ratio"]).iloc[-1]

        print("\n" + "=" * 80)
        print("  虚实盘比因子分析")
        print("=" * 80)
        print("\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  主力合约: {latest['dominant_code']}")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  成交量: {latest['vol']:.0f}")
        print(f"  持仓量: {latest['oi']:.0f}")
        print(f"  虚实盘比: {latest['virtual_real_ratio']:.3f}")
        print(f"  持仓变化: {latest['oi_change']:+.0f}")
        print(f"  成交变化: {latest['vol_change']:+.0f}")
        print(f"  比值Z分数: {latest['ratio_zscore']:+.2f}")
        print(f"  交易信号: {latest['signal']}")
        print(f"  信号解读: {latest['signal_text']}")

        print("\n【历史统计】")
        print(f"  样本数量: {factor_data['virtual_real_ratio'].notna().sum()}")
        print(f"  均值: {factor_data['virtual_real_ratio'].mean():.3f}")
        print(f"  中位数: {factor_data['virtual_real_ratio'].median():.3f}")
        print(f"  25%分位: {factor_data['virtual_real_ratio'].quantile(0.25):.3f}")
        print(f"  75%分位: {factor_data['virtual_real_ratio'].quantile(0.75):.3f}")
        print("=" * 80 + "\n")

        return factor_data, latest.to_dict()


def main() -> None:
    """单文件运行入口。"""
    parser = argparse.ArgumentParser(description="虚实盘比因子测试")
    parser.add_argument("--product", default="NI", help="品种代码，默认 NI")
    args = parser.parse_args()
    product = args.product.upper()

    print("=" * 60)
    print(f"{product} 虚实盘比因子测试")
    print("=" * 60)

    cache_file = os.path.join(PROJECT_ROOT, "data", "processed", f"{product.lower()}_contracts_daily.csv")
    if not os.path.exists(cache_file):
        raise FileNotFoundError(
            f"未找到真实历史数据: {cache_file}。"
            f"请先运行 `python run_factors.py history --product {product}` 生成缓存后，再执行虚实盘比分析。"
        )

    print(f"\n从缓存加载数据: {cache_file}")
    contracts_data = pd.read_csv(cache_file, dtype={"trade_date": str})
    dominant_data = load_dominant_contract_features(contracts_data)

    factor = VirtualRealRatioFactor()
    factor.print_analysis_report(dominant_data)


if __name__ == "__main__":
    main()

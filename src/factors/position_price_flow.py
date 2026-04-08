"""
持仓-价格联动因子模块。

核心思路：
- 价格上涨 + 持仓增加：多头增仓
- 价格下跌 + 持仓增加：空头增仓
- 价格上涨 + 持仓减少：空头回补
- 价格下跌 + 持仓减少：多头离场

该模块支持：
- 基于主力合约日线的历史信号序列
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


def load_dominant_contract_data(contracts_data: pd.DataFrame) -> pd.DataFrame:
    """从全合约数据中提取每日主力合约。"""
    df = contracts_data.copy()
    df["trade_date"] = df["trade_date"].astype(str)

    idx = df.groupby("trade_date")["oi"].idxmax()
    dominant = df.loc[idx, ["trade_date", "ts_code", "close", "oi", "vol"]].copy()
    dominant.columns = ["trade_date", "dominant_code", "close", "oi", "vol"]
    dominant["trade_date"] = pd.to_datetime(dominant["trade_date"])
    dominant = dominant.sort_values("trade_date").reset_index(drop=True)
    return dominant


class PositionPriceFlowFactor:
    """持仓-价格联动因子。"""

    SIGNAL_SCORE = {
        "long_buildup": 2,
        "short_covering": 1,
        "neutral": 0,
        "long_unwinding": -1,
        "short_buildup": -2,
    }

    def __init__(self, ths_client=None):
        self.ths_client = ths_client

    def _get_ths_client(self):
        if self.ths_client is None:
            from src.data_fetcher.ths_client import THSClient

            self.ths_client = THSClient()
        return self.ths_client

    def calc_factor_values(self, dominant_data: pd.DataFrame) -> pd.DataFrame:
        """计算历史持仓-价格联动因子。"""
        df = dominant_data.copy().sort_values("trade_date").reset_index(drop=True)
        df["price_change"] = df["close"].pct_change()
        df["oi_change"] = df["oi"].diff()
        df["oi_change_pct"] = df["oi"].pct_change()
        df["vol_change"] = df["vol"].diff()
        df["vol_oi_ratio"] = df["vol"] / df["oi"].replace(0, np.nan)

        df["price_move_threshold"] = (
            df["price_change"].abs().rolling(20, min_periods=5).median().clip(lower=0.002)
        )
        df["oi_move_threshold"] = (
            df["oi_change_pct"].abs().rolling(20, min_periods=5).median().clip(lower=0.005)
        )

        df = self.generate_signals(df)
        df["position_flow_score"] = df["signal"].map(self.SIGNAL_SCORE).fillna(0)
        return df

    def generate_signals(self, factor_data: pd.DataFrame) -> pd.DataFrame:
        """根据信号象限生成交易含义。"""
        df = factor_data.copy()
        price_change = df["price_change"]
        oi_change_pct = df["oi_change_pct"]
        price_threshold = df["price_move_threshold"]
        oi_threshold = df["oi_move_threshold"]

        price_up = price_change >= price_threshold
        price_down = price_change <= -price_threshold
        oi_up = oi_change_pct >= oi_threshold
        oi_down = oi_change_pct <= -oi_threshold

        df["signal"] = "neutral"
        df["signal_text"] = "价格与持仓变化均不显著，资金方向暂不明确"
        df["regime"] = "震荡观望"

        df.loc[price_up & oi_up, "signal"] = "long_buildup"
        df.loc[price_up & oi_up, "signal_text"] = "价格上涨且增仓，偏向多头增仓、资金流入"
        df.loc[price_up & oi_up, "regime"] = "多头增仓"

        df.loc[price_down & oi_up, "signal"] = "short_buildup"
        df.loc[price_down & oi_up, "signal_text"] = "价格下跌且增仓，偏向空头增仓、情绪偏空"
        df.loc[price_down & oi_up, "regime"] = "空头增仓"

        df.loc[price_up & oi_down, "signal"] = "short_covering"
        df.loc[price_up & oi_down, "signal_text"] = "价格上涨但减仓，更像空头回补推动的反弹"
        df.loc[price_up & oi_down, "regime"] = "空头回补"

        df.loc[price_down & oi_down, "signal"] = "long_unwinding"
        df.loc[price_down & oi_down, "signal_text"] = "价格下跌且减仓，偏向多头离场、趋势衰减"
        df.loc[price_down & oi_down, "regime"] = "多头离场"
        return df

    def fetch_realtime_snapshot(self, contract_code: str) -> Dict:
        """获取单个合约的实时快照。"""
        client = self._get_ths_client()
        quote = client.get_realtime_quote(contract_code)
        if not quote:
            raise ValueError(f"未获取到实时行情: {contract_code}")

        latest = float(quote.get("latest", 0))
        pre_close = float(quote.get("preClose", 0))
        open_interest = float(quote.get("openInterest", 0))
        volume = float(quote.get("volume", 0))
        amount = float(quote.get("amount", 0))

        return {
            "contract_code": contract_code,
            "latest": latest,
            "pre_close": pre_close,
            "price_change": (latest / pre_close - 1) if pre_close > 0 else np.nan,
            "open_interest": open_interest,
            "volume": volume,
            "amount": amount,
            "vol_oi_ratio": volume / open_interest if open_interest > 0 else np.nan,
            "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def interpret_snapshot(self, snapshot: Dict, reference_snapshot: Optional[Dict] = None) -> Dict:
        """结合参考持仓基准解读实时信号。"""
        result = snapshot.copy()
        oi_change = np.nan
        vol_change = np.nan
        oi_change_pct = np.nan

        if reference_snapshot is not None:
            ref_oi = float(reference_snapshot.get("open_interest", reference_snapshot.get("oi", 0)) or 0)
            ref_vol = float(reference_snapshot.get("volume", reference_snapshot.get("vol", 0)) or 0)
            if ref_oi > 0:
                oi_change = snapshot["open_interest"] - ref_oi
                oi_change_pct = oi_change / ref_oi
            vol_change = snapshot["volume"] - ref_vol

        price_change = snapshot["price_change"]
        price_threshold = max(abs(price_change) * 0.3, 0.002) if pd.notna(price_change) else 0.002
        oi_threshold = 0.005

        signal = "neutral"
        regime = "震荡观望"
        signal_text = "价格与持仓变化均不显著，资金方向暂不明确"

        if pd.notna(price_change) and pd.notna(oi_change_pct):
            if price_change >= price_threshold and oi_change_pct >= oi_threshold:
                signal = "long_buildup"
                regime = "多头增仓"
                signal_text = "实时价格上涨且持仓增加，偏向多头资金继续流入"
            elif price_change <= -price_threshold and oi_change_pct >= oi_threshold:
                signal = "short_buildup"
                regime = "空头增仓"
                signal_text = "实时价格下跌且持仓增加，偏向空头资金发力"
            elif price_change >= price_threshold and oi_change_pct <= -oi_threshold:
                signal = "short_covering"
                regime = "空头回补"
                signal_text = "实时价格上涨但持仓减少，更像空头回补带来的反弹"
            elif price_change <= -price_threshold and oi_change_pct <= -oi_threshold:
                signal = "long_unwinding"
                regime = "多头离场"
                signal_text = "实时价格下跌且持仓减少，偏向多头离场或下跌衰减"

        result["oi_change"] = oi_change
        result["oi_change_pct"] = oi_change_pct
        result["vol_change"] = vol_change
        result["signal"] = signal
        result["regime"] = regime
        result["signal_text"] = signal_text
        return result

    def print_analysis_report(self, dominant_data: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """打印历史因子摘要。"""
        factor_data = self.calc_factor_values(dominant_data)
        latest = factor_data.dropna(subset=["price_change", "oi_change"]).iloc[-1]

        regime_count = factor_data["regime"].value_counts()

        print("\n" + "=" * 80)
        print("  持仓-价格联动因子分析")
        print("=" * 80)
        print("\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  主力合约: {latest['dominant_code']}")
        print(f"  收盘价: {latest['close']:.2f}")
        print(f"  当日涨跌: {latest['price_change']*100:+.2f}%")
        print(f"  持仓量: {latest['oi']:.0f}")
        print(f"  持仓变化: {latest['oi_change']:+.0f}")
        print(f"  持仓变化率: {latest['oi_change_pct']*100:+.2f}%")
        print(f"  成交量: {latest['vol']:.0f}")
        print(f"  量仓比: {latest['vol_oi_ratio']:.3f}")
        print(f"  联动结构: {latest['regime']}")
        print(f"  交易信号: {latest['signal']}")
        print(f"  信号解读: {latest['signal_text']}")

        print("\n【历史结构分布】")
        print(f"  样本数量: {factor_data['price_change'].notna().sum()}")
        print(f"  多头增仓占比: {regime_count.get('多头增仓', 0) / max(len(factor_data), 1) * 100:.1f}%")
        print(f"  空头增仓占比: {regime_count.get('空头增仓', 0) / max(len(factor_data), 1) * 100:.1f}%")
        print(f"  空头回补占比: {regime_count.get('空头回补', 0) / max(len(factor_data), 1) * 100:.1f}%")
        print(f"  多头离场占比: {regime_count.get('多头离场', 0) / max(len(factor_data), 1) * 100:.1f}%")
        print(f"  震荡观望占比: {regime_count.get('震荡观望', 0) / max(len(factor_data), 1) * 100:.1f}%")
        print("=" * 80 + "\n")

        return factor_data, latest.to_dict()


def main() -> None:
    """单文件运行入口。"""
    parser = argparse.ArgumentParser(description="持仓-价格联动因子测试")
    parser.add_argument("--product", default="NI", help="品种代码，默认 NI")
    args = parser.parse_args()
    product = args.product.upper()

    print("=" * 60)
    print(f"{product} 持仓-价格联动因子测试")
    print("=" * 60)

    cache_file = os.path.join(PROJECT_ROOT, "data", "processed", f"{product.lower()}_contracts_daily.csv")
    if not os.path.exists(cache_file):
        raise FileNotFoundError(
            f"未找到真实历史数据: {cache_file}。"
            f"请先运行 `python run_factors.py history --product {product}` 生成缓存后，再执行持仓联动分析。"
        )

    print(f"\n从缓存加载数据: {cache_file}")
    contracts_data = pd.read_csv(cache_file, dtype={"trade_date": str})
    dominant_data = load_dominant_contract_data(contracts_data)

    factor = PositionPriceFlowFactor()
    factor.print_analysis_report(dominant_data)


if __name__ == "__main__":
    main()

"""VIX + RSI 沪镍恐慌反转回测模块。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.factors.macd import load_dominant_price
from src.strategies.vix_panic_reversion import VIXPanicReversionStrategy


class NickelVIXPanicReversionStrategy(VIXPanicReversionStrategy):
    """沪镍版 VIX + RSI 恐慌反转策略。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 镍版沿用原版的开平仓规则，只是把底层标的从标普500替换成沪镍主力连续。
        # 也就是说，这里研究的是“全球风险情绪上升时，沪镍是否存在类似的恐慌反转机会”。
        self.underlying_name = "沪镍主力连续"
        self.chart_title = "VIX + RSI 沪镍恐慌反转策略"


def main() -> None:
    parser = argparse.ArgumentParser(description="VIX + RSI 沪镍恐慌反转回测")
    parser.add_argument("--input-file", default=str(PROJECT_ROOT / "data" / "processed" / "ni_contracts_daily.csv"), help="沪镍历史缓存文件")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "processed" / "ni_vix_panic_reversion"), help="输出目录")
    parser.add_argument("--start-date", default="2015-04-01", help="起始日期")
    parser.add_argument("--end-date", default=None, help="结束日期")
    args = parser.parse_args()

    from src.data_fetcher.fred_client import FredClient

    contracts_data = pd.read_csv(args.input_file, dtype={"trade_date": str})
    # 每日取持仓量最大的沪镍合约，构造连续主力价格序列。
    price_data = load_dominant_price(contracts_data)[["trade_date", "close"]].copy()

    fred = FredClient()
    # 情绪过滤变量仍使用 VIX，不单独构造本土波动率指标。
    vix_data = fred.get_series("VIXCLS", start_date=args.start_date, end_date=args.end_date)

    strategy = NickelVIXPanicReversionStrategy()
    merged = strategy.prepare_data(price_data, vix_data)
    signal_data = strategy.signal_generation(merged)
    portfolio = strategy.backtest(signal_data)
    strategy.print_report(portfolio)
    paths = strategy.export_results(portfolio, Path(args.output_dir))
    print(f"结果已导出到: {args.output_dir}/")
    print(f"导出文件: {paths}")


if __name__ == "__main__":
    main()

"""VIX + RSI 恐慌反转回测模块。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.plotting import setup_chinese_font

setup_chinese_font()


def smma(series: pd.Series, window: int) -> np.ndarray:
    """计算平滑移动平均。"""
    values = np.asarray(series, dtype=float)
    if len(values) == 0:
        return np.array([])

    output = [values[0]]
    for i in range(1, len(values)):
        output.append((output[-1] * (window - 1) + values[i]) / window)
    return np.array(output)


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """计算 RSI 指标。"""
    delta = series.diff().dropna()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)

    avg_up = smma(pd.Series(up), window)
    avg_down = smma(pd.Series(down), window)
    rs = np.divide(avg_up, avg_down, out=np.zeros_like(avg_up), where=avg_down != 0)
    values = 100 - 100 / (1 + rs)
    return pd.Series(values[window - 1 :], index=series.index[window:])


class VIXPanicReversionStrategy:
    """VIX + RSI 恐慌反转策略。"""

    def __init__(
        self,
        rsi_window: int = 14,
        rsi_entry: float = 30,
        rsi_exit: float = 55,
        vix_window: int = 20,
        vix_z_entry: float = 1.0,
        max_holding_days: int = 10,
        capital0: float = 10000.0,
    ):
        self.rsi_window = rsi_window
        self.rsi_entry = rsi_entry
        self.rsi_exit = rsi_exit
        self.vix_window = vix_window
        self.vix_z_entry = vix_z_entry
        self.max_holding_days = max_holding_days
        self.capital0 = capital0
        self.underlying_name = "标普500指数"
        self.chart_title = "VIX + RSI 恐慌反转策略"

    def prepare_data(self, price_data: pd.DataFrame, vix_data: pd.DataFrame) -> pd.DataFrame:
        """合并标的价格与 VIX。"""
        df = pd.merge(price_data, vix_data, on="trade_date", how="inner")
        df = df.rename(columns={"close": "Close", "vixcls": "VIX", "sp500": "Close"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.sort_values("trade_date").reset_index(drop=True)

    def signal_generation(self, df: pd.DataFrame) -> pd.DataFrame:
        """生成信号与仓位。"""
        data = df.copy()
        # RSI 用来识别价格是否已经进入短期超卖区间。
        data["rsi"] = np.nan
        rsi_values = rsi(data["Close"], self.rsi_window)
        data.loc[data.index[self.rsi_window :], "rsi"] = rsi_values.values

        # VIX 的 Z 分数衡量“当前恐慌是否显著高于近期常态”。
        data["vix_mean"] = data["VIX"].rolling(self.vix_window).mean()
        data["vix_std"] = data["VIX"].rolling(self.vix_window).std()
        data["vix_z"] = (data["VIX"] - data["vix_mean"]) / data["vix_std"]

        data["signal"] = 0
        data["position"] = 0
        data["holding_days"] = 0

        holding = 0
        holding_days = 0
        start_idx = max(self.rsi_window, self.vix_window)

        for i in range(start_idx, len(data)):
            current_rsi = data.at[i, "rsi"]
            current_vix_z = data.at[i, "vix_z"]
            current_vix = data.at[i, "VIX"]
            current_vix_mean = data.at[i, "vix_mean"]

            if holding == 0:
                if pd.notna(current_rsi) and pd.notna(current_vix_z):
                    # 只有在“价格超卖 + 市场恐慌放大”同时出现时才开仓，
                    # 避免把普通回调误判成恐慌反转机会。
                    if current_rsi <= self.rsi_entry and current_vix_z >= self.vix_z_entry:
                        data.at[i, "signal"] = 1
                        holding = 1
                        holding_days = 1
            else:
                holding_days += 1
                # 平仓条件分三类：
                # 1. RSI 回到相对中性偏强区域，说明反弹已兑现一部分；
                # 2. VIX 回落到均值附近，说明恐慌缓解；
                # 3. 持有天数达到上限，避免反转交易拖成长持仓。
                should_exit = (
                    (pd.notna(current_rsi) and current_rsi >= self.rsi_exit)
                    or (pd.notna(current_vix_mean) and current_vix <= current_vix_mean)
                    or (holding_days >= self.max_holding_days)
                )
                if should_exit:
                    data.at[i, "signal"] = -1
                    holding = 0
                    holding_days = 0

            data.at[i, "position"] = holding
            data.at[i, "holding_days"] = holding_days

        # 用下一根K线执行信号，避免用当日收盘信息在同一根K线上成交。
        data["strategy_position"] = data["position"].shift(1).fillna(0)
        return data.dropna().reset_index(drop=True)

    def backtest(self, signal_data: pd.DataFrame) -> pd.DataFrame:
        """执行回测。"""
        portfolio = signal_data.copy()
        portfolio["buy_hold_return"] = portfolio["Close"].pct_change().fillna(0)
        # 策略收益只在持仓时承接标的涨跌；空仓时收益为 0。
        portfolio["strategy_return"] = portfolio["buy_hold_return"] * portfolio["strategy_position"]
        portfolio["buy_hold_equity"] = self.capital0 * (1 + portfolio["buy_hold_return"]).cumprod()
        portfolio["strategy_equity"] = self.capital0 * (1 + portfolio["strategy_return"]).cumprod()
        return portfolio

    def summarize(self, portfolio: pd.DataFrame) -> pd.Series:
        """生成绩效摘要。"""
        strategy_ret = portfolio["strategy_return"]
        buy_hold_ret = portfolio["buy_hold_return"]

        summary = {
            "strategy_total_return": portfolio["strategy_equity"].iloc[-1] / self.capital0 - 1,
            "buy_hold_total_return": portfolio["buy_hold_equity"].iloc[-1] / self.capital0 - 1,
            "strategy_annualized_return": (1 + strategy_ret.mean()) ** 252 - 1,
            "buy_hold_annualized_return": (1 + buy_hold_ret.mean()) ** 252 - 1,
            "strategy_annualized_vol": strategy_ret.std() * np.sqrt(252),
            "buy_hold_annualized_vol": buy_hold_ret.std() * np.sqrt(252),
            "strategy_sharpe": np.sqrt(252) * strategy_ret.mean() / strategy_ret.std() if strategy_ret.std() else np.nan,
            "buy_hold_sharpe": np.sqrt(252) * buy_hold_ret.mean() / buy_hold_ret.std() if buy_hold_ret.std() else np.nan,
            "strategy_max_drawdown": (portfolio["strategy_equity"] / portfolio["strategy_equity"].cummax() - 1).min(),
            "buy_hold_max_drawdown": (portfolio["buy_hold_equity"] / portfolio["buy_hold_equity"].cummax() - 1).min(),
            "trades": int((portfolio["signal"] == 1).sum()),
            "exposure": portfolio["strategy_position"].mean(),
        }
        return pd.Series(summary)

    def plot(self, portfolio: pd.DataFrame, output_path: Path, ticker: str | None = None) -> Path:
        """导出策略图表。"""
        ticker = ticker or self.underlying_name
        fig = plt.figure(figsize=(12, 10))

        ax1 = fig.add_subplot(311)
        ax1.plot(portfolio["trade_date"], portfolio["Close"], color="#264653", lw=1.5, label=ticker)
        ax1.plot(
            portfolio.loc[portfolio["signal"] == 1, "trade_date"],
            portfolio.loc[portfolio["signal"] == 1, "Close"],
            marker="^",
            lw=0,
            c="#2a9d8f",
            markersize=7,
            label="开多",
        )
        ax1.plot(
            portfolio.loc[portfolio["signal"] == -1, "trade_date"],
            portfolio.loc[portfolio["signal"] == -1, "Close"],
            marker="v",
            lw=0,
            c="#d62828",
            markersize=7,
            label="平仓",
        )
        ax1.set_title(self.chart_title)
        ax1.set_ylabel("价格")
        ax1.grid(alpha=0.2)
        ax1.legend()

        ax2 = fig.add_subplot(312, sharex=ax1)
        ax2.plot(portfolio["trade_date"], portfolio["rsi"], color="#6d597a", lw=1.2, label="RSI")
        ax2.axhline(self.rsi_entry, color="#d62828", ls="--", alpha=0.7, label="RSI开仓阈值")
        ax2.axhline(self.rsi_exit, color="#457b9d", ls="--", alpha=0.7, label="RSI平仓阈值")
        ax2.set_ylabel("RSI")
        ax2.grid(alpha=0.2)
        ax2.legend()

        ax3 = fig.add_subplot(313, sharex=ax1)
        ax3.plot(portfolio["trade_date"], portfolio["strategy_equity"], color="#1d3557", lw=1.5, label="策略净值")
        ax3.plot(portfolio["trade_date"], portfolio["buy_hold_equity"], color="#a8dadc", lw=1.3, label="买入持有")
        ax3.set_ylabel("净值")
        ax3.set_xlabel("日期")
        ax3.grid(alpha=0.2)
        ax3.legend()

        fig.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return output_path

    def export_results(self, portfolio: pd.DataFrame, output_dir: Path) -> Dict[str, Path]:
        """导出结果文件。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        signal_path = output_dir / "signals.csv"
        summary_path = output_dir / "summary.csv"
        chart_path = output_dir / "backtest_chart.png"
        latest_summary_path = output_dir / "latest_summary.md"

        portfolio.to_csv(signal_path, index=False)
        summary = self.summarize(portfolio)
        summary.to_frame(name="value").to_csv(summary_path)
        self.plot(portfolio, chart_path)

        latest = portfolio.iloc[-1]
        latest_summary_path.write_text(
            "\n".join(
                [
                    "# VIX + RSI 恐慌反转摘要",
                    "",
                    f"- 日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}",
                    f"- 标的（{self.underlying_name}）收盘价: {latest['Close']:.2f}",
                    f"- VIX: {latest['VIX']:.2f}",
                    f"- RSI: {latest['rsi']:.2f}",
                    f"- VIX Z分数: {latest['vix_z']:.2f}",
                    f"- 当前策略仓位（{self.underlying_name}）: {int(latest['strategy_position']):+d}",
                    f"- 当前仓位说明: {self._position_text(int(latest['strategy_position']))}",
                    f"- 本次持仓天数: {int(latest['holding_days'])}",
                    f"- 策略累计收益: {summary['strategy_total_return']*100:+.2f}%",
                    f"- 买入持有收益: {summary['buy_hold_total_return']*100:+.2f}%",
                    f"- 夏普比率: {summary['strategy_sharpe']:.2f}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        return {
            "signals": signal_path,
            "summary": summary_path,
            "chart": chart_path,
            "latest_summary": latest_summary_path,
        }

    def _position_text(self, position: int) -> str:
        """解释当前策略仓位。"""
        if position > 0:
            return f"做多{self.underlying_name}"
        if position < 0:
            return f"做空{self.underlying_name}"
        return f"空仓，未持有{self.underlying_name}"

    def print_report(self, portfolio: pd.DataFrame) -> pd.Series:
        """打印回测结果。"""
        summary = self.summarize(portfolio)
        latest = portfolio.iloc[-1]
        current_position = int(latest["strategy_position"])

        print("\n" + "=" * 80)
        print("  VIX + RSI 恐慌反转回测")
        print("=" * 80)
        print("\n【最新状态】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  标的（{self.underlying_name}）收盘价: {latest['Close']:.2f}")
        print(f"  VIX: {latest['VIX']:.2f}")
        print(f"  RSI: {latest['rsi']:.2f}")
        print(f"  VIX Z分数: {latest['vix_z']:.2f}")
        print(f"  当前策略仓位（{self.underlying_name}）: {current_position:+d}")
        print(f"  当前仓位说明: {self._position_text(current_position)}")
        print(f"  本次持仓天数: {int(latest['holding_days'])}")

        print("\n【绩效指标】")
        print(f"  策略累计收益: {summary['strategy_total_return']*100:+.2f}%")
        print(f"  买入持有收益: {summary['buy_hold_total_return']*100:+.2f}%")
        print(f"  策略年化收益: {summary['strategy_annualized_return']*100:+.2f}%")
        print(f"  买入持有年化收益: {summary['buy_hold_annualized_return']*100:+.2f}%")
        print(f"  策略波动率: {summary['strategy_annualized_vol']*100:.2f}%")
        print(f"  买入持有波动率: {summary['buy_hold_annualized_vol']*100:.2f}%")
        print(f"  策略夏普: {summary['strategy_sharpe']:.2f}")
        print(f"  买入持有夏普: {summary['buy_hold_sharpe']:.2f}")
        print(f"  策略最大回撤: {summary['strategy_max_drawdown']*100:.2f}%")
        print(f"  买入持有最大回撤: {summary['buy_hold_max_drawdown']*100:.2f}%")
        print(f"  开仓次数: {int(summary['trades'])}")
        print(f"  平均仓位暴露: {summary['exposure']*100:.2f}%")
        print("=" * 80 + "\n")
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="VIX + RSI 恐慌反转回测")
    parser.add_argument("--start-date", default="2010-01-01", help="起始日期")
    parser.add_argument("--end-date", default=None, help="结束日期")
    parser.add_argument("--input-file", default="", help="预先准备好的 CSV 文件")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "processed" / "vix_panic_reversion"), help="输出目录")
    args = parser.parse_args()

    strategy = VIXPanicReversionStrategy()

    if args.input_file:
        df = pd.read_csv(args.input_file, parse_dates=["trade_date"])
    else:
        from src.data_fetcher.fred_client import FredClient

        fred = FredClient()
        # 原版策略研究的是“美股恐慌后反转”，因此底层标的是标普500，情绪变量是 VIX。
        price_data = fred.get_series("SP500", start_date=args.start_date, end_date=args.end_date)
        vix_data = fred.get_series("VIXCLS", start_date=args.start_date, end_date=args.end_date)
        df = strategy.prepare_data(price_data, vix_data)

    signal_data = strategy.signal_generation(df)
    portfolio = strategy.backtest(signal_data)
    strategy.print_report(portfolio)
    paths = strategy.export_results(portfolio, Path(args.output_dir))
    print(f"结果已导出到: {args.output_dir}/")
    print(f"导出文件: {paths}")


if __name__ == "__main__":
    main()

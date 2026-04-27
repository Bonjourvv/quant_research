"""
MACD因子模块

参数：
- 快线EMA: 12日
- 慢线EMA: 26日
- 信号线: 9日

信号逻辑：
- 金叉（DIF上穿DEA）：做多信号
- 死叉（DIF下穿DEA）：做空信号

计算标的：主力合约连续价格
"""

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.plotting import plot_seasonal_chart, setup_chinese_font
from src.denoise import add_switch_noise_flag, rolling_median_series

setup_chinese_font()


class MACDFactor:
    """MACD因子计算器"""
    
    def __init__(
            self,
            fast_period: int = 12,
            slow_period: int = 26,
            signal_period: int = 9,
            denoise: bool = False,
            smooth_window: int = 3,
    ):
        """
        初始化
        
        Args:
            fast_period: 快线EMA周期
            slow_period: 慢线EMA周期
            signal_period: 信号线EMA周期
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.denoise = denoise
        self.smooth_window = smooth_window
    
    def calc_ema(self, series: pd.Series, period: int) -> pd.Series:
        """
        计算EMA（指数移动平均）
        
        Args:
            series: 价格序列
            period: 周期
            
        Returns:
            EMA序列
        """
        return series.ewm(span=period, adjust=False).mean()
    
    def calc_macd(self, price_data: pd.DataFrame) -> pd.DataFrame:
        """
        计算MACD指标
        
        Args:
            price_data: 价格数据，需包含 trade_date, close
            
        Returns:
            DataFrame with columns:
                trade_date, close, ema_fast, ema_slow, dif, dea, macd_hist
        """
        df = price_data.copy()
        df = df.sort_values('trade_date').reset_index(drop=True)
        if self.denoise:
            df['close_raw'] = df['close']
            df['close'] = rolling_median_series(df['close'], self.smooth_window)
        
        # 计算EMA
        df['ema_fast'] = self.calc_ema(df['close'], self.fast_period)
        df['ema_slow'] = self.calc_ema(df['close'], self.slow_period)
        
        # DIF = 快线EMA - 慢线EMA
        df['dif'] = df['ema_fast'] - df['ema_slow']
        
        # DEA = DIF的EMA（信号线）
        df['dea'] = self.calc_ema(df['dif'], self.signal_period)
        
        # MACD柱 = (DIF - DEA) * 2
        df['macd_hist'] = (df['dif'] - df['dea']) * 2
        
        return df

    def classify_trend(self, macd_data: pd.DataFrame) -> pd.DataFrame:
        """基于DIF/DEA位置和斜率识别趋势状态。"""
        df = macd_data.copy()
        df["dif_slope"] = df["dif"].diff()
        df["dea_slope"] = df["dea"].diff()
        df["hist_slope"] = df["macd_hist"].diff()

        df["trend"] = "sideways"
        strong_up = (
            (df["dif"] > df["dea"]) &
            (df["dif"] > 0) &
            (df["dea"] > 0) &
            (df["hist_slope"] > 0)
        )
        weak_up = (
            (df["dif"] > df["dea"]) &
            ((df["dif_slope"] > 0) | (df["dea_slope"] > 0))
        )
        strong_down = (
            (df["dif"] < df["dea"]) &
            (df["dif"] < 0) &
            (df["dea"] < 0) &
            (df["hist_slope"] < 0)
        )
        weak_down = (
            (df["dif"] < df["dea"]) &
            ((df["dif_slope"] < 0) | (df["dea_slope"] < 0))
        )

        df.loc[weak_up, "trend"] = "uptrend"
        df.loc[strong_up, "trend"] = "strong_uptrend"
        df.loc[weak_down, "trend"] = "downtrend"
        df.loc[strong_down, "trend"] = "strong_downtrend"
        return df

    def summarize_latest_trend(self, signal_data: pd.DataFrame) -> Dict:
        """提取最新趋势摘要。"""
        latest = signal_data.iloc[-1]
        return {
            "trade_date": latest["trade_date"],
            "close": latest["close"],
            "dif": latest["dif"],
            "dea": latest["dea"],
            "macd_hist": latest["macd_hist"],
            "signal": int(latest["signal"]),
            "position": int(latest["position"]),
            "trend": latest.get("trend", "sideways"),
        }
    
    def generate_signals(self, macd_data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        金叉：DIF从下向上穿越DEA → 做多信号 (1)
        死叉：DIF从上向下穿越DEA → 做空信号 (-1)
        其他：维持前一信号 (0表示初始无信号)
        
        Args:
            macd_data: MACD数据，需包含 dif, dea
            
        Returns:
            添加 signal, position 列的DataFrame
        """
        df = self.classify_trend(macd_data.copy())
        
        # 计算DIF与DEA的差值
        df['dif_minus_dea'] = df['dif'] - df['dea']
        
        # 前一日的差值
        df['prev_diff'] = df['dif_minus_dea'].shift(1)
        
        # 金叉：前一日DIF<DEA，今日DIF>=DEA
        df['golden_cross'] = (df['prev_diff'] < 0) & (df['dif_minus_dea'] >= 0)
        
        # 死叉：前一日DIF>DEA，今日DIF<=DEA
        df['death_cross'] = (df['prev_diff'] > 0) & (df['dif_minus_dea'] <= 0)
        
        # 信号：金叉=1，死叉=-1，其他=0
        df['signal'] = 0
        df.loc[df['golden_cross'], 'signal'] = 1
        df.loc[df['death_cross'], 'signal'] = -1
        if self.denoise and 'switch_noise' in df.columns:
            df.loc[df['switch_noise'], 'signal'] = 0
        
        # 持仓：信号发出后一直持有，直到反向信号
        df['position'] = 0
        position = 0
        positions = []
        
        for i, row in df.iterrows():
            if row['signal'] == 1:
                position = 1
            elif row['signal'] == -1:
                position = -1
            positions.append(position)
        
        df['position'] = positions
        
        df = df.drop(columns=['dif_minus_dea', 'prev_diff', 'golden_cross', 'death_cross'])
        
        return df
    
    def calc_factor_values(self, price_data: pd.DataFrame) -> pd.DataFrame:
        """
        计算MACD因子值（用于IC分析）
        
        因子值定义：MACD柱状图值（标准化）
        
        Args:
            price_data: 价格数据
            
        Returns:
            DataFrame with trade_date, macd_factor
        """
        df = self.calc_macd(price_data)
        
        # 标准化MACD柱状图作为因子值
        df['macd_factor'] = df['macd_hist'] / df['close'] * 100  # 转为百分比
        
        return df[['trade_date', 'close', 'dif', 'dea', 'macd_hist', 'macd_factor', 'signal', 'position']] if 'signal' in df.columns else df
    
    def calc_returns(self, signal_data: pd.DataFrame, holding_periods: List[int] = [1, 3, 5, 10, 20]) -> pd.DataFrame:
        """
        计算信号后的收益
        
        Args:
            signal_data: 含信号的数据
            holding_periods: 持有周期列表
            
        Returns:
            添加各周期收益列的DataFrame
        """
        df = signal_data.copy()
        
        for n in holding_periods:
            df[f'fwd_ret_{n}d'] = df['close'].shift(-n) / df['close'] - 1
        
        return df
    
    def analyze_signals(self, signal_data: pd.DataFrame, holding_periods: List[int] = [1, 3, 5, 10, 20]) -> Dict:
        """
        分析信号表现
        
        Args:
            signal_data: 含信号的数据
            holding_periods: 持有周期
            
        Returns:
            各周期的信号表现统计
        """
        df = self.calc_returns(signal_data, holding_periods)
        
        results = {}
        
        for period in holding_periods:
            ret_col = f'fwd_ret_{period}d'
            
            # 金叉信号表现
            golden = df[df['signal'] == 1]
            golden_ret = golden[ret_col].dropna()
            
            # 死叉信号表现
            death = df[df['signal'] == -1]
            death_ret = death[ret_col].dropna()
            
            results[period] = {
                'golden_cross_count': len(golden),
                'golden_cross_ret_mean': golden_ret.mean() if len(golden_ret) > 0 else np.nan,
                'golden_cross_win_rate': (golden_ret > 0).mean() if len(golden_ret) > 0 else np.nan,
                
                'death_cross_count': len(death),
                'death_cross_ret_mean': death_ret.mean() if len(death_ret) > 0 else np.nan,
                'death_cross_win_rate': (death_ret < 0).mean() if len(death_ret) > 0 else np.nan,  # 做空跌了算赢
                
                'long_short_diff': (golden_ret.mean() if len(golden_ret) > 0 else 0) - 
                                   (death_ret.mean() if len(death_ret) > 0 else 0),
            }
        
        return results
    
    def print_analysis_report(self, price_data: pd.DataFrame, holding_periods: List[int] = [1, 3, 5, 10, 20]):
        """
        打印MACD因子分析报告
        
        Args:
            price_data: 价格数据
            holding_periods: 持有周期
        """
        print("\n" + "=" * 80)
        print(f"  MACD因子分析报告 (参数: {self.fast_period}, {self.slow_period}, {self.signal_period})")
        print("=" * 80)
        
        # 计算MACD和信号
        macd_data = self.calc_macd(price_data)
        signal_data = self.generate_signals(macd_data)
        
        # 数据概况
        print(f"\n【数据概况】")
        print(f"  时间范围: {signal_data['trade_date'].min()} ~ {signal_data['trade_date'].max()}")
        print(f"  样本数量: {len(signal_data)}")
        
        # 信号统计
        golden_count = (signal_data['signal'] == 1).sum()
        death_count = (signal_data['signal'] == -1).sum()
        
        print(f"\n【信号统计】")
        print(f"  金叉信号: {golden_count} 次")
        print(f"  死叉信号: {death_count} 次")
        print(f"  信号频率: 平均每 {len(signal_data) / (golden_count + death_count):.1f} 个交易日一次信号")

        latest = self.summarize_latest_trend(signal_data)
        print(f"\n【当前趋势】")
        print(f"  日期: {pd.to_datetime(latest['trade_date']).strftime('%Y-%m-%d')}")
        print(f"  当前趋势: {latest['trend']}")
        print(f"  DIF / DEA: {latest['dif']:.2f} / {latest['dea']:.2f}")
        print(f"  MACD柱: {latest['macd_hist']:.2f}")
        print(f"  当前信号: {latest['signal']:+d}")
        print(f"  当前持仓: {latest['position']:+d}")
        
        # 各周期表现
        results = self.analyze_signals(signal_data, holding_periods)
        
        print(f"\n【信号表现分析】")
        print(f"  {'周期':<8} {'金叉次数':>10} {'金叉收益':>12} {'金叉胜率':>10} "
              f"{'死叉次数':>10} {'死叉收益':>12} {'死叉胜率':>10} {'多空差':>12}")
        print("  " + "-" * 90)
        
        for period in holding_periods:
            r = results[period]
            print(f"  {period}日{'':<5} "
                  f"{r['golden_cross_count']:>10} "
                  f"{r['golden_cross_ret_mean']*100:>+11.3f}% "
                  f"{r['golden_cross_win_rate']*100:>9.1f}% "
                  f"{r['death_cross_count']:>10} "
                  f"{r['death_cross_ret_mean']*100:>+11.3f}% "
                  f"{r['death_cross_win_rate']*100:>9.1f}% "
                  f"{r['long_short_diff']*100:>+11.3f}%")
        
        # 结论
        print(f"\n【结论】")
        r5 = results.get(5, results.get(list(results.keys())[0]))
        
        if r5['golden_cross_win_rate'] > 0.5 and r5['death_cross_win_rate'] > 0.5:
            effectiveness = "有效（金叉做多、死叉做空均有效）"
        elif r5['golden_cross_win_rate'] > 0.5:
            effectiveness = "部分有效（仅金叉做多有效）"
        elif r5['death_cross_win_rate'] > 0.5:
            effectiveness = "部分有效（仅死叉做空有效）"
        else:
            effectiveness = "弱/无效"
        
        print(f"  因子有效性: {effectiveness}")
        print(f"  5日周期 - 金叉胜率: {r5['golden_cross_win_rate']*100:.1f}%, 死叉胜率: {r5['death_cross_win_rate']*100:.1f}%")
        
        print("=" * 80 + "\n")
        
        return signal_data, results

    def plot_macd_chart(self, signal_data: pd.DataFrame, output_path: str) -> str:
        """导出价格与MACD趋势图。"""
        df = signal_data.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])

        fig, (ax_price, ax_macd) = plt.subplots(
            2,
            1,
            figsize=(12, 8),
            sharex=True,
            gridspec_kw={"height_ratios": [2, 1]},
        )

        ax_price.plot(df["trade_date"], df["close"], color="#1f2937", linewidth=1.6, label="收盘价")
        long_points = df[df["signal"] == 1]
        short_points = df[df["signal"] == -1]
        ax_price.scatter(long_points["trade_date"], long_points["close"], color="#2a9d8f", s=24, label="金叉")
        ax_price.scatter(short_points["trade_date"], short_points["close"], color="#d62828", s=24, label="死叉")
        ax_price.set_title("主力合约价格与MACD信号")
        ax_price.set_ylabel("价格")
        ax_price.legend()
        ax_price.grid(alpha=0.2)

        bar_colors = np.where(df["macd_hist"] >= 0, "#2a9d8f", "#d62828")
        ax_macd.bar(df["trade_date"], df["macd_hist"], color=bar_colors, alpha=0.6, label="MACD柱")
        ax_macd.plot(df["trade_date"], df["dif"], color="#264653", linewidth=1.3, label="DIF")
        ax_macd.plot(df["trade_date"], df["dea"], color="#e76f51", linewidth=1.3, label="DEA")
        ax_macd.axhline(0, color="black", linewidth=1, linestyle="--")
        ax_macd.set_title("MACD指标")
        ax_macd.set_ylabel("指标值")
        ax_macd.legend()
        ax_macd.grid(alpha=0.2)

        fig.tight_layout()
        fig.savefig(output_path, dpi=320)
        plt.close(fig)
        return output_path

    def export_results(self, signal_data: pd.DataFrame, output_dir: str = 'data/processed'):
        """
        导出结果
        
        Args:
            signal_data: 信号数据
            output_dir: 输出目录
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 导出MACD数据
        signal_data.to_csv(f'{output_dir}/macd_signals.csv', index=False)
        self.plot_macd_chart(signal_data, f'{output_dir}/macd_chart.png')
        plot_seasonal_chart(
            signal_data,
            value_col="macd_hist",
            output_path=f"{output_dir}/macd_seasonal.png",
            title="MACD季节图（2022-2026）",
            y_label="MACD柱",
        )
        
        print(f"MACD数据已导出到: {output_dir}/macd_signals.csv")


class MACDICAnalyzer:
    """MACD因子IC分析器"""
    
    def __init__(self, macd_data: pd.DataFrame):
        """
        初始化
        
        Args:
            macd_data: MACD数据，需包含 trade_date, close, macd_hist
        """
        self.data = macd_data.copy()
        self.data['trade_date'] = pd.to_datetime(self.data['trade_date'])
    
    def calc_ic(self, periods: List[int] = [1, 3, 5, 10, 20]) -> pd.DataFrame:
        """
        计算MACD因子与未来收益的IC
        
        Args:
            periods: 收益周期
            
        Returns:
            各周期IC统计
        """
        from scipy import stats
        
        df = self.data.copy()
        results = []
        
        for period in periods:
            # 计算未来收益
            df[f'fwd_ret_{period}d'] = df['close'].shift(-period) / df['close'] - 1
            
            valid = df[['macd_hist', f'fwd_ret_{period}d']].dropna()
            
            if len(valid) > 30:
                ic, pvalue = stats.spearmanr(valid['macd_hist'], valid[f'fwd_ret_{period}d'])
            else:
                ic, pvalue = np.nan, np.nan
            
            results.append({
                'period': f'{period}D',
                'ic': ic,
                'pvalue': pvalue,
                'sample_size': len(valid)
            })
        
        return pd.DataFrame(results)
    
    def print_ic_report(self, periods: List[int] = [1, 3, 5, 10, 20]):
        """打印IC报告"""
        print("\n【MACD因子IC分析】")
        
        ic_summary = self.calc_ic(periods)
        
        print(f"  {'周期':<8} {'IC':>10} {'p值':>12} {'样本数':>10}")
        print("  " + "-" * 44)
        
        for _, row in ic_summary.iterrows():
            print(f"  {row['period']:<8} {row['ic']:>10.4f} {row['pvalue']:>12.4f} {int(row['sample_size']):>10}")
        
        print(f"\n  解读:")
        print(f"  - IC > 0 表示MACD柱越大，未来收益越高")
        print(f"  - |IC| > 0.03 通常认为因子有效")


def load_dominant_price(contracts_data: pd.DataFrame) -> pd.DataFrame:
    """
    从合约数据中提取主力合约连续价格
    
    Args:
        contracts_data: 所有合约数据
        
    Returns:
        主力合约价格序列
    """
    df = contracts_data.copy()
    df['trade_date'] = df['trade_date'].astype(str)
    
    # 每日取持仓量最大的合约作为主力
    idx = df.groupby('trade_date')['oi'].idxmax()
    dominant = df.loc[idx][['trade_date', 'ts_code', 'close', 'oi']].copy()
    dominant.columns = ['trade_date', 'dominant_code', 'close', 'oi']
    
    dominant['trade_date'] = pd.to_datetime(dominant['trade_date'])
    dominant = dominant.sort_values('trade_date').reset_index(drop=True)
    dominant = add_switch_noise_flag(dominant, code_col='dominant_code')
    return dominant


def main():
    """测试MACD因子"""
    parser = argparse.ArgumentParser(description="MACD因子测试")
    parser.add_argument("--product", default="NI", help="品种代码，默认 NI")
    args = parser.parse_args()
    product = args.product.upper()

    print("=" * 60)
    print(f"{product} MACD因子测试")
    print("=" * 60)
    
    cache_file = os.path.join(PROJECT_ROOT, 'data', 'processed', f'{product.lower()}_contracts_daily.csv')
    
    if not os.path.exists(cache_file):
        raise FileNotFoundError(
            f"未找到真实历史数据: {cache_file}。"
            f"请先运行 `python run_factors.py history --product {product}` 生成缓存后，再执行 MACD 分析。"
        )

    print(f"\n从缓存加载数据: {cache_file}")
    contracts_data = pd.read_csv(cache_file, dtype={'trade_date': str})

    price_data = load_dominant_price(contracts_data)
    print(f"主力合约价格数据: {len(price_data)} 条")
    
    # 计算MACD并分析
    macd = MACDFactor(12, 26, 9)
    signal_data, results = macd.print_analysis_report(price_data)
    
    # IC分析
    macd_data = macd.calc_macd(price_data)
    ic_analyzer = MACDICAnalyzer(macd_data)
    ic_analyzer.print_ic_report()


if __name__ == '__main__':
    main()

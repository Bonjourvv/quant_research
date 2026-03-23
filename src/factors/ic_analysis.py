"""
展期收益率因子IC分析模块

功能：
- 计算因子IC（Information Coefficient）：因子值与未来收益率的相关性
- IC统计：IC均值、IC标准差、ICIR、IC胜率
- 分组收益分析：按因子值分组，比较各组收益
- 因子有效性评估

说明：
- IC < 0 表示展期收益率与未来收益负相关（贴水利于做多）
- |IC| > 0.03 通常认为因子有效
- ICIR > 0.5 是不错的因子
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from typing import Dict, List, Tuple
import os

from src.plotting import setup_chinese_font

setup_chinese_font()


class FactorICAnalyzer:
    """因子IC分析器"""
    
    def __init__(
            self,
            factor_data: pd.DataFrame,
            price_data: pd.DataFrame,
            factor_col: str = 'roll_yield',
            factor_name: str = 'roll_yield',
            lower_factor_is_bullish: bool = True,
    ):
        """
        初始化
        
        Args:
            factor_data: 因子数据，需包含 trade_date, roll_yield
            price_data: 价格数据，需包含 trade_date, close
        """
        self.factor_data = factor_data.copy()
        self.price_data = price_data.copy()
        self.factor_col = factor_col
        self.factor_name = factor_name
        self.lower_factor_is_bullish = lower_factor_is_bullish
        self.data = self._prepare_data()

    def _factor_label_zh(self) -> str:
        """返回因子的中文展示名。"""
        mapping = {
            "roll_yield": "展期收益率",
            "momentum": "价格动量",
            "macd": "MACD",
        }
        return mapping.get(self.factor_name, self.factor_name)
        
    def _prepare_data(self) -> pd.DataFrame:
        """准备分析数据"""
        self.factor_data['trade_date'] = pd.to_datetime(self.factor_data['trade_date'])
        self.price_data['trade_date'] = pd.to_datetime(self.price_data['trade_date'])
        
        df = pd.merge(
            self.factor_data[['trade_date', self.factor_col]],
            self.price_data[['trade_date', 'close']],
            on='trade_date',
            how='inner'
        )

        df = df.rename(columns={self.factor_col: 'factor_value'})
        
        return df.sort_values('trade_date').reset_index(drop=True)
    
    def calc_forward_returns(self, periods: List[int] = [1, 3, 5, 10, 20]) -> pd.DataFrame:
        """计算未来N日收益率"""
        df = self.data.copy()
        
        for n in periods:
            df[f'fwd_ret_{n}d'] = df['close'].shift(-n) / df['close'] - 1
        
        return df
    
    def calc_ic_series(self, period: int = 5, method: str = 'spearman') -> Tuple:
        """计算IC"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        valid = df[['trade_date', 'factor_value', ret_col]].dropna()
        
        if method == 'spearman':
            ic, pvalue = stats.spearmanr(valid['factor_value'], valid[ret_col])
        else:
            ic, pvalue = stats.pearsonr(valid['factor_value'], valid[ret_col])
        
        return ic, pvalue, valid
    
    def calc_rolling_ic(self, period: int = 5, window: int = 60) -> pd.DataFrame:
        """计算滚动IC"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        
        rolling_ic = df['factor_value'].rolling(window).corr(df[ret_col])
        
        return pd.DataFrame({
            'trade_date': df['trade_date'],
            'ic': rolling_ic
        })
    
    def calc_ic_summary(self, periods: List[int] = [1, 3, 5, 10, 20]) -> pd.DataFrame:
        """计算各周期IC汇总统计"""
        results = []
        
        for period in periods:
            ic, pvalue, valid = self.calc_ic_series(period, 'spearman')
            rolling_ic = self.calc_rolling_ic(period, 60)
            ic_values = rolling_ic['ic'].dropna()
            
            results.append({
                'period': f'{period}D',
                'ic': ic,
                'pvalue': pvalue,
                'ic_mean': ic_values.mean(),
                'ic_std': ic_values.std(),
                'icir': ic_values.mean() / ic_values.std() if ic_values.std() > 0 else 0,
                'ic_positive_rate': (ic_values > 0).mean(),
                'sample_size': len(valid)
            })
        
        return pd.DataFrame(results)
    
    def calc_group_returns(self, period: int = 5, n_groups: int = 5) -> Tuple:
        """分组收益分析"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        valid = df[['factor_value', ret_col]].dropna().copy()
        
        valid['group'] = pd.qcut(valid['factor_value'], n_groups, labels=range(1, n_groups + 1), duplicates='drop')
        
        group_stats = valid.groupby('group').agg({
            'factor_value': ['mean', 'min', 'max'],
            ret_col: ['mean', 'std', 'count']
        })
        group_stats.columns = ['factor_mean', 'factor_min', 'factor_max', 'ret_mean', 'ret_std', 'count']
        group_stats = group_stats.reset_index()

        first_group = group_stats['group'].min()
        last_group = group_stats['group'].max()

        if self.lower_factor_is_bullish:
            long_short = group_stats[group_stats['group'] == first_group]['ret_mean'].values[0] - \
                         group_stats[group_stats['group'] == last_group]['ret_mean'].values[0]
        else:
            long_short = group_stats[group_stats['group'] == last_group]['ret_mean'].values[0] - \
                         group_stats[group_stats['group'] == first_group]['ret_mean'].values[0]
        
        return group_stats, long_short
    
    def calc_quantile_spread(self, period: int = 5, long_q: float = 0.25, short_q: float = 0.75) -> Dict:
        """计算分位数多空组合收益"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        valid = df[['factor_value', ret_col]].dropna()
        
        long_threshold = valid['factor_value'].quantile(long_q)
        short_threshold = valid['factor_value'].quantile(short_q)

        if self.lower_factor_is_bullish:
            long_group = valid[valid['factor_value'] <= long_threshold]
            short_group = valid[valid['factor_value'] >= short_threshold]
        else:
            long_group = valid[valid['factor_value'] >= short_threshold]
            short_group = valid[valid['factor_value'] <= long_threshold]
        
        return {
            'period': period,
            'long_threshold': long_threshold,
            'short_threshold': short_threshold,
            'long_count': len(long_group),
            'long_ret_mean': long_group[ret_col].mean(),
            'long_win_rate': (long_group[ret_col] > 0).mean(),
            'short_count': len(short_group),
            'short_ret_mean': short_group[ret_col].mean(),
            'short_win_rate': (short_group[ret_col] < 0).mean(),
            'long_short_ret': long_group[ret_col].mean() - short_group[ret_col].mean(),
        }

    def run_quantile_backtest(self, period: int = 3, long_q: float = 0.25, short_q: float = 0.75) -> pd.DataFrame:
        """按因子分位数构建持有期为 period 的多空策略净值。"""
        df = self.data.copy().sort_values("trade_date").reset_index(drop=True)

        lower = df["factor_value"].quantile(long_q)
        upper = df["factor_value"].quantile(short_q)

        if self.lower_factor_is_bullish:
            signal = np.where(df["factor_value"] <= lower, 1, np.where(df["factor_value"] >= upper, -1, 0))
        else:
            signal = np.where(df["factor_value"] >= upper, 1, np.where(df["factor_value"] <= lower, -1, 0))

        df["signal"] = signal

        # 未来 period 日总收益，作为这次开仓的持有期收益
        df["period_forward_ret"] = df["close"].shift(-period) / df["close"] - 1
        df["strategy_period_ret"] = df["signal"] * df["period_forward_ret"]
        df["benchmark_period_ret"] = df["period_forward_ret"]

        rebalance = df.iloc[::period].copy()
        rebalance = rebalance.dropna(subset=["period_forward_ret"]).reset_index(drop=True)
        rebalance["strategy_nav"] = (1 + rebalance["strategy_period_ret"].fillna(0)).cumprod()
        rebalance["benchmark_nav"] = (1 + rebalance["benchmark_period_ret"].fillna(0)).cumprod()
        rebalance["holding_period"] = period
        return rebalance

    def plot_backtest_charts(
        self,
        output_dir: str = "output",
        prefix: str = "factor",
        chart_period: int = 3,
    ) -> Dict[str, str]:
        """导出回测与诊断图。"""
        os.makedirs(output_dir, exist_ok=True)

        backtest = self.run_quantile_backtest(period=chart_period)
        rolling_ic = self.calc_rolling_ic(chart_period)
        group_stats, _ = self.calc_group_returns(chart_period, 5)

        nav_path = os.path.join(output_dir, f"{prefix}_backtest_nav.png")
        ic_path = os.path.join(output_dir, f"{prefix}_rolling_ic.png")
        group_path = os.path.join(output_dir, f"{prefix}_group_returns.png")

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(backtest["trade_date"], backtest["strategy_nav"], label="策略净值", linewidth=2)
        ax.plot(backtest["trade_date"], backtest["benchmark_nav"], label="基准净值", linewidth=1.5, alpha=0.8)
        ax.set_title(f"{self._factor_label_zh()}分位数组合回测净值（{chart_period}日持有）")
        ax.set_ylabel("净值")
        ax.grid(alpha=0.2)
        ax.legend()
        fig.tight_layout()
        fig.savefig(nav_path, dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(rolling_ic["trade_date"], rolling_ic["ic"], color="#1f77b4", linewidth=1.5)
        ax.axhline(0, color="black", linewidth=1, linestyle="--")
        ax.set_title(f"{self._factor_label_zh()}滚动IC（{chart_period}日收益，60日窗口）")
        ax.set_ylabel("IC")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(ic_path, dpi=160)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(group_stats["group"].astype(str), group_stats["ret_mean"] * 100, color="#2a6f97")
        ax.set_title(f"{self._factor_label_zh()}分组收益（{chart_period}日）")
        ax.set_xlabel("分组")
        ax.set_ylabel("平均收益率 (%)")
        ax.axhline(0, color="black", linewidth=1)
        ax.grid(axis="y", alpha=0.2)
        fig.tight_layout()
        fig.savefig(group_path, dpi=160)
        plt.close(fig)

        return {
            "nav_chart": nav_path,
            "rolling_ic_chart": ic_path,
            "group_chart": group_path,
        }
    
    def print_analysis_report(self, periods: List[int] = [1, 3, 5, 10, 20]):
        """打印完整分析报告"""
        print("\n" + "=" * 80)
        print(f"  {self.factor_name} 因子 IC 分析报告")
        print("=" * 80)
        
        df = self.data
        print(f"\n【数据概况】")
        print(f"  时间范围: {df['trade_date'].min().strftime('%Y-%m-%d')} ~ "
              f"{df['trade_date'].max().strftime('%Y-%m-%d')}")
        print(f"  样本数量: {len(df)}")
        print(f"  {self.factor_name}均值: {df['factor_value'].mean()*100:.2f}%")
        print(f"  {self.factor_name}标准差: {df['factor_value'].std()*100:.2f}%")
        
        # IC统计
        print(f"\n【IC统计 (Spearman)】")
        ic_summary = self.calc_ic_summary(periods)
        
        print(f"  {'周期':<8} {'IC':>10} {'IC均值':>10} {'IC标准差':>10} "
              f"{'ICIR':>8} {'IC>0占比':>10} {'p值':>10}")
        print("  " + "-" * 70)
        for _, row in ic_summary.iterrows():
            print(f"  {row['period']:<8} {row['ic']:>10.4f} {row['ic_mean']:>10.4f} "
                  f"{row['ic_std']:>10.4f} {row['icir']:>8.2f} "
                  f"{row['ic_positive_rate']*100:>9.1f}% {row['pvalue']:>10.4f}")
        
        print(f"\n  解读:")
        print(f"  - IC 的符号表示 {self.factor_name} 与未来收益的方向关系")
        print(f"  - |IC| > 0.03 通常认为因子有效")
        print(f"  - ICIR > 0.5 是较好的因子")
        
        # 分组收益
        print(f"\n【分组收益分析 (5组, 5日收益)】")
        group_stats, long_short = self.calc_group_returns(5, 5)
        
        print(f"  {'组别':>6} {'因子区间':>24} {'平均收益':>12} {'样本数':>8}")
        print("  " + "-" * 54)
        for _, row in group_stats.iterrows():
            ry_range = f"[{row['factor_min']*100:+.1f}%, {row['factor_max']*100:+.1f}%]"
            print(f"  {int(row['group']):>6} {ry_range:>24} {row['ret_mean']*100:>+11.3f}% {int(row['count']):>8}")

        print(f"\n  多空组合收益差: {long_short*100:+.3f}%")
        
        # 分位数策略
        print(f"\n【分位数策略分析 (25%/75%分位)】")
        for period in [3, 5, 10, 20]:
            result = self.calc_quantile_spread(period)
            print(f"\n  {period}日周期:")
            print(f"    做多组(阈值={result['long_threshold']*100:.2f}%): "
                  f"收益{result['long_ret_mean']*100:+.3f}%, 胜率{result['long_win_rate']*100:.1f}%")
            print(f"    做空组(阈值={result['short_threshold']*100:.2f}%): "
                  f"收益{result['short_ret_mean']*100:+.3f}%, 胜率{result['short_win_rate']*100:.1f}%")
            print(f"    多空收益差: {result['long_short_ret']*100:+.3f}%")
        
        # 结论
        print(f"\n【结论】")
        main_ic = ic_summary[ic_summary['period'] == '5D']['ic'].values[0]
        main_icir = ic_summary[ic_summary['period'] == '5D']['icir'].values[0]
        
        if abs(main_ic) > 0.03:
            direction = "负相关" if main_ic < 0 else "正相关"
            effectiveness = f"有效（{direction}）"
        else:
            effectiveness = "弱/无效"
        
        print(f"  因子有效性: {effectiveness}")
        print(f"  5日IC: {main_ic:.4f}, ICIR: {main_icir:.2f}")
        
        print("=" * 80 + "\n")
    
    def export_results(self, output_dir: str = 'output'):
        """导出分析结果"""
        os.makedirs(output_dir, exist_ok=True)
        
        self.calc_ic_summary().to_csv(f'{output_dir}/ic_summary.csv', index=False)
        self.calc_rolling_ic(5).to_csv(f'{output_dir}/rolling_ic_5d.csv', index=False)
        self.calc_rolling_ic(3).to_csv(f'{output_dir}/rolling_ic_3d.csv', index=False)
        self.calc_group_returns(5, 5)[0].to_csv(f'{output_dir}/group_returns.csv', index=False)
        self.calc_group_returns(3, 5)[0].to_csv(f'{output_dir}/group_returns_3d.csv', index=False)
        self.calc_forward_returns().to_csv(f'{output_dir}/factor_returns.csv', index=False)
        self.run_quantile_backtest(period=3).to_csv(f'{output_dir}/backtest_nav.csv', index=False)
        chart_paths = self.plot_backtest_charts(output_dir, self.factor_name, chart_period=3)
        
        print(f"分析结果已导出到: {output_dir}/")
        print(f"图表已导出到: {chart_paths}")

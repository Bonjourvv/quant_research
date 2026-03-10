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
from scipy import stats
from typing import Dict, List, Tuple
import os


class FactorICAnalyzer:
    """因子IC分析器"""
    
    def __init__(
            self,
            factor_data: pd.DataFrame,
            price_data: pd.DataFrame
    ):
        """
        初始化
        
        Args:
            factor_data: 因子数据，需包含 trade_date, roll_yield
            price_data: 价格数据，需包含 trade_date, close
        """
        self.factor_data = factor_data.copy()
        self.price_data = price_data.copy()
        self.data = self._prepare_data()
        
    def _prepare_data(self) -> pd.DataFrame:
        """准备分析数据"""
        self.factor_data['trade_date'] = pd.to_datetime(self.factor_data['trade_date'])
        self.price_data['trade_date'] = pd.to_datetime(self.price_data['trade_date'])
        
        df = pd.merge(
            self.factor_data[['trade_date', 'roll_yield']],
            self.price_data[['trade_date', 'close']],
            on='trade_date',
            how='inner'
        )
        
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
        valid = df[['trade_date', 'roll_yield', ret_col]].dropna()
        
        if method == 'spearman':
            ic, pvalue = stats.spearmanr(valid['roll_yield'], valid[ret_col])
        else:
            ic, pvalue = stats.pearsonr(valid['roll_yield'], valid[ret_col])
        
        return ic, pvalue, valid
    
    def calc_rolling_ic(self, period: int = 5, window: int = 60) -> pd.DataFrame:
        """计算滚动IC"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        
        rolling_ic = df['roll_yield'].rolling(window).corr(df[ret_col])
        
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
        valid = df[['roll_yield', ret_col]].dropna()
        
        valid['group'] = pd.qcut(valid['roll_yield'], n_groups, labels=range(1, n_groups + 1))
        
        group_stats = valid.groupby('group').agg({
            'roll_yield': ['mean', 'min', 'max'],
            ret_col: ['mean', 'std', 'count']
        })
        group_stats.columns = ['ry_mean', 'ry_min', 'ry_max', 'ret_mean', 'ret_std', 'count']
        group_stats = group_stats.reset_index()
        
        long_short = group_stats[group_stats['group'] == 1]['ret_mean'].values[0] - \
                     group_stats[group_stats['group'] == n_groups]['ret_mean'].values[0]
        
        return group_stats, long_short
    
    def calc_quantile_spread(self, period: int = 5, long_q: float = 0.25, short_q: float = 0.75) -> Dict:
        """计算分位数多空组合收益"""
        df = self.calc_forward_returns([period])
        ret_col = f'fwd_ret_{period}d'
        valid = df[['roll_yield', ret_col]].dropna()
        
        long_threshold = valid['roll_yield'].quantile(long_q)
        short_threshold = valid['roll_yield'].quantile(short_q)
        
        long_group = valid[valid['roll_yield'] <= long_threshold]
        short_group = valid[valid['roll_yield'] >= short_threshold]
        
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
    
    def print_analysis_report(self, periods: List[int] = [1, 3, 5, 10, 20]):
        """打印完整分析报告"""
        print("\n" + "=" * 80)
        print("  展期收益率因子 IC 分析报告")
        print("=" * 80)
        
        df = self.data
        print(f"\n【数据概况】")
        print(f"  时间范围: {df['trade_date'].min().strftime('%Y-%m-%d')} ~ "
              f"{df['trade_date'].max().strftime('%Y-%m-%d')}")
        print(f"  样本数量: {len(df)}")
        print(f"  展期收益率均值: {df['roll_yield'].mean()*100:.2f}%")
        print(f"  展期收益率标准差: {df['roll_yield'].std()*100:.2f}%")
        
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
        print(f"  - IC < 0 表示展期收益率与未来收益负相关（贴水利于做多）")
        print(f"  - |IC| > 0.03 通常认为因子有效")
        print(f"  - ICIR > 0.5 是较好的因子")
        
        # 分组收益
        print(f"\n【分组收益分析 (5组, 5日收益)】")
        group_stats, long_short = self.calc_group_returns(5, 5)
        
        print(f"  {'组别':>6} {'展期收益率区间':>24} {'平均收益':>12} {'样本数':>8}")
        print("  " + "-" * 54)
        for _, row in group_stats.iterrows():
            ry_range = f"[{row['ry_min']*100:+.1f}%, {row['ry_max']*100:+.1f}%]"
            print(f"  {int(row['group']):>6} {ry_range:>24} {row['ret_mean']*100:>+11.3f}% {int(row['count']):>8}")
        
        print(f"\n  第1组(贴水深) vs 第5组(升水深) 收益差: {long_short*100:+.3f}%")
        
        # 分位数策略
        print(f"\n【分位数策略分析 (25%/75%分位)】")
        for period in [3, 5, 10, 20]:
            result = self.calc_quantile_spread(period)
            print(f"\n  {period}日周期:")
            print(f"    做多组(RY≤{result['long_threshold']*100:.2f}%): "
                  f"收益{result['long_ret_mean']*100:+.3f}%, 胜率{result['long_win_rate']*100:.1f}%")
            print(f"    做空组(RY≥{result['short_threshold']*100:.2f}%): "
                  f"收益{result['short_ret_mean']*100:+.3f}%, 胜率{result['short_win_rate']*100:.1f}%")
            print(f"    多空收益差: {result['long_short_ret']*100:+.3f}%")
        
        # 结论
        print(f"\n【结论】")
        main_ic = ic_summary[ic_summary['period'] == '5D']['ic'].values[0]
        main_icir = ic_summary[ic_summary['period'] == '5D']['icir'].values[0]
        
        if main_ic < -0.03:
            effectiveness = "有效（负相关，贴水利于做多）"
        elif main_ic > 0.03:
            effectiveness = "有效（正相关，升水利于做多）"
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
        self.calc_group_returns()[0].to_csv(f'{output_dir}/group_returns.csv', index=False)
        self.calc_forward_returns().to_csv(f'{output_dir}/factor_returns.csv', index=False)
        
        print(f"分析结果已导出到: {output_dir}/")

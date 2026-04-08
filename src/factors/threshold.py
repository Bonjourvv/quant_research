"""
展期收益率阈值计算模块

功能：
- 基于历史数据计算分位数阈值
- 支持滚动窗口计算动态阈值
- 生成交易信号
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
import os


class ThresholdCalculator:
    """阈值计算器"""
    
    def __init__(self, history_data: pd.DataFrame = None):
        """
        初始化
        
        Args:
            history_data: 历史展期收益率数据，需包含 trade_date, roll_yield 列
        """
        self.history = history_data
        
    def load_history(self, file_path: str) -> pd.DataFrame:
        """从CSV加载历史数据"""
        self.history = pd.read_csv(file_path, parse_dates=['trade_date'])
        print(f"加载历史数据: {len(self.history)} 条记录")
        return self.history
    
    def calc_fixed_threshold(
            self,
            bullish_quantile: float = 0.25,
            bearish_quantile: float = 0.75
    ) -> Dict:
        """
        计算固定阈值（全历史分位数）
        
        Args:
            bullish_quantile: 做多阈值分位数（默认25%，贴水区域）
            bearish_quantile: 做空阈值分位数（默认75%，升水区域）
        """
        if self.history is None:
            raise ValueError("请先加载历史数据")
        
        ry = self.history['roll_yield'].dropna()
        
        return {
            'bullish_threshold': ry.quantile(bullish_quantile),
            'bearish_threshold': ry.quantile(bearish_quantile),
            'mean': ry.mean(),
            'std': ry.std(),
            'min': ry.min(),
            'max': ry.max(),
            'quantiles': {
                '5%': ry.quantile(0.05),
                '10%': ry.quantile(0.10),
                '25%': ry.quantile(0.25),
                '50%': ry.quantile(0.50),
                '75%': ry.quantile(0.75),
                '90%': ry.quantile(0.90),
                '95%': ry.quantile(0.95),
            },
            'sample_size': len(ry),
            'bullish_quantile': bullish_quantile,
            'bearish_quantile': bearish_quantile,
        }
    
    def calc_rolling_threshold(
            self,
            window: int = 252,
            bullish_quantile: float = 0.25,
            bearish_quantile: float = 0.75
    ) -> pd.DataFrame:
        """计算滚动窗口阈值"""
        if self.history is None:
            raise ValueError("请先加载历史数据")
        
        df = self.history.copy().sort_values('trade_date')
        
        df['rolling_mean'] = df['roll_yield'].rolling(window, min_periods=window//2).mean()
        df['rolling_std'] = df['roll_yield'].rolling(window, min_periods=window//2).std()
        df['bullish_threshold'] = df['roll_yield'].rolling(window, min_periods=window//2).quantile(bullish_quantile)
        df['bearish_threshold'] = df['roll_yield'].rolling(window, min_periods=window//2).quantile(bearish_quantile)
        
        return df
    
    def generate_signal(
            self,
            current_ry: float,
            bullish_threshold: float,
            bearish_threshold: float
    ) -> int:
        """生成交易信号：1=做多, -1=做空, 0=空仓"""
        if pd.isna(current_ry):
            return 0
        
        if current_ry <= bullish_threshold:
            return 1
        elif current_ry >= bearish_threshold:
            return -1
        else:
            return 0
    
    def add_signals(
            self,
            data: pd.DataFrame = None,
            bullish_threshold: float = None,
            bearish_threshold: float = None,
            use_rolling: bool = False,
            rolling_window: int = 252
    ) -> pd.DataFrame:
        """为数据添加交易信号列"""
        if data is None:
            data = self.history
        
        df = data.copy()
        
        if use_rolling:
            df = self.calc_rolling_threshold(rolling_window)
            df['signal'] = df.apply(
                lambda row: self.generate_signal(
                    row['roll_yield'],
                    row['bullish_threshold'],
                    row['bearish_threshold']
                ),
                axis=1
            )
        else:
            if bullish_threshold is None or bearish_threshold is None:
                thresholds = self.calc_fixed_threshold()
                bullish_threshold = thresholds['bullish_threshold']
                bearish_threshold = thresholds['bearish_threshold']
            
            df['bullish_threshold'] = bullish_threshold
            df['bearish_threshold'] = bearish_threshold
            df['signal'] = df['roll_yield'].apply(
                lambda ry: self.generate_signal(ry, bullish_threshold, bearish_threshold)
            )
        
        return df
    
    def print_threshold_report(self, thresholds: Dict = None):
        """打印阈值报告"""
        if thresholds is None:
            thresholds = self.calc_fixed_threshold()
        
        print("=" * 60)
        print("展期收益率阈值报告")
        print("=" * 60)
        
        print(f"\n样本量: {thresholds['sample_size']} 个交易日")
        
        print(f"\n统计特征:")
        print(f"  均值:   {thresholds['mean']*100:>8.2f}%")
        print(f"  标准差: {thresholds['std']*100:>8.2f}%")
        print(f"  最小值: {thresholds['min']*100:>8.2f}%")
        print(f"  最大值: {thresholds['max']*100:>8.2f}%")
        
        print(f"\n分位数分布:")
        for q, v in thresholds['quantiles'].items():
            print(f"  {q}: {v*100:>8.2f}%")
        
        print(f"\n交易阈值:")
        print(f"  做多阈值 ({thresholds['bullish_quantile']:.0%}分位): {thresholds['bullish_threshold']*100:>8.2f}%")
        print(f"  做空阈值 ({thresholds['bearish_quantile']:.0%}分位): {thresholds['bearish_threshold']*100:>8.2f}%")
        
        print(f"\n信号逻辑:")
        print(f"  展期收益率 ≤ {thresholds['bullish_threshold']*100:.2f}% → 做多")
        print(f"  展期收益率 ≥ {thresholds['bearish_threshold']*100:.2f}% → 做空")
        print(f"  其他 → 空仓")
        
        print("=" * 60)

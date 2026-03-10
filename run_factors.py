#!/usr/bin/env python3
"""
沪镍展期收益率因子分析

功能：
1. realtime  - 显示实时展期收益率表格（所有合约对）
2. history   - 计算历史展期收益率序列
3. threshold - 计算分位数阈值
4. ic        - IC分析（因子与收益率相关性）
5. all       - 运行全部（默认）

使用方法:
    python run_factors.py [mode]
    
示例:
    python run_factors.py realtime   # 只看实时表格
    python run_factors.py ic         # 只做IC分析
    python run_factors.py            # 运行全部
"""

import os
import sys
from datetime import datetime
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from src.factors.roll_yield import RollYieldFactor, RollYieldHistory
from src.factors.threshold import ThresholdCalculator
from src.factors.ic_analysis import FactorICAnalyzer

# ============================================================
# 配置参数
# ============================================================
CONFIG = {
    # 数据参数
    'product': 'NI',
    'start_date': '20150401',      # 沪镍2015年3月上市
    'end_date': None,              # None=今天
    
    # 展期收益率计算
    'ry_method': 'weighted_avg',   # weighted_avg/simple_avg/median
    'min_oi': 1000,                # 最小持仓量过滤
    
    # 阈值
    'bullish_quantile': 0.25,      # 做多阈值：25%分位
    'bearish_quantile': 0.75,      # 做空阈值：75%分位
    
    # 缓存和输出
    'use_cache': True,
    'cache_dir': 'data/processed',
    'output_dir': 'data/processed',
}


def run_realtime(config: dict):
    """模式1: 实时展期收益率表格"""
    print("\n" + "=" * 80)
    print("  [实时] 展期收益率表格")
    print("=" * 80)
    
    factor = RollYieldFactor()
    
    for product in ['ni', 'ss']:
        contracts_df, pairs_df, summary = factor.print_realtime_table(product)
        
        # 保存到文件
        if not pairs_df.empty:
            os.makedirs(config['output_dir'], exist_ok=True)
            pairs_df.to_csv(
                f"{config['output_dir']}/{product}_realtime_pairs.csv",
                index=False
            )


def run_history(config: dict):
    """模式2: 计算历史展期收益率"""
    print("\n" + "=" * 80)
    print("  [历史] 展期收益率计算")
    print("=" * 80)
    
    from src.data_fetcher.tushare_client import TushareClient
    
    # 缓存文件
    contracts_cache = os.path.join(config['cache_dir'], f"{config['product'].lower()}_contracts_daily.csv")
    ry_cache = os.path.join(config['cache_dir'], f"{config['product'].lower()}_roll_yield_{config['ry_method']}.csv")
    
    # 加载合约数据
    if config['use_cache'] and os.path.exists(contracts_cache):
        print(f"从缓存加载合约数据: {contracts_cache}")
        contracts_data = pd.read_csv(contracts_cache, dtype={'trade_date': str})
    else:
        print("从Tushare获取合约数据...")
        ts_client = TushareClient()
        calc = RollYieldHistory(ts_client)
        
        end_date = config['end_date'] or datetime.now().strftime('%Y%m%d')
        contracts_data = calc.load_all_contracts_data(
            product=config['product'],
            start_date=config['start_date'],
            end_date=end_date,
            cache_file=contracts_cache
        )
    
    print(f"合约数据: {len(contracts_data)} 条记录")
    
    # 计算展期收益率
    if config['use_cache'] and os.path.exists(ry_cache):
        print(f"从缓存加载展期收益率: {ry_cache}")
        ry_data = pd.read_csv(ry_cache, parse_dates=['trade_date'])
    else:
        print("计算历史展期收益率...")
        calc = RollYieldHistory()
        calc._data_cache = contracts_data
        
        ry_data = calc.calc_history_roll_yield(
            method=config['ry_method'],
            min_oi=config['min_oi']
        )
        
        os.makedirs(config['cache_dir'], exist_ok=True)
        ry_data.to_csv(ry_cache, index=False)
        print(f"已保存到: {ry_cache}")
    
    # 统计信息
    print(f"\n【历史展期收益率统计】")
    print(f"  时间范围: {ry_data['trade_date'].min()} ~ {ry_data['trade_date'].max()}")
    print(f"  样本数量: {len(ry_data)}")
    print(f"  均值: {ry_data['roll_yield'].mean()*100:.2f}%")
    print(f"  标准差: {ry_data['roll_yield'].std()*100:.2f}%")
    print(f"  最小值: {ry_data['roll_yield'].min()*100:.2f}%")
    print(f"  最大值: {ry_data['roll_yield'].max()*100:.2f}%")
    
    return ry_data, contracts_data


def run_threshold(config: dict, ry_data: pd.DataFrame):
    """模式3: 计算阈值"""
    print("\n" + "=" * 80)
    print("  [阈值] 分位数计算")
    print("=" * 80)
    
    calc = ThresholdCalculator(ry_data)
    thresholds = calc.calc_fixed_threshold(
        bullish_quantile=config['bullish_quantile'],
        bearish_quantile=config['bearish_quantile']
    )
    
    calc.print_threshold_report(thresholds)
    
    return thresholds


def run_ic_analysis(config: dict, ry_data: pd.DataFrame, contracts_data: pd.DataFrame):
    """模式4: IC分析"""
    print("\n" + "=" * 80)
    print("  [IC] 因子相关性分析")
    print("=" * 80)
    
    # 准备价格数据（每日主力合约收盘价）
    contracts_data['trade_date'] = contracts_data['trade_date'].astype(str)
    idx = contracts_data.groupby('trade_date')['oi'].idxmax()
    price_data = contracts_data.loc[idx][['trade_date', 'close']].copy()
    price_data['trade_date'] = pd.to_datetime(price_data['trade_date'])
    price_data = price_data.sort_values('trade_date')
    
    print(f"价格数据: {len(price_data)} 条")
    
    # IC分析
    analyzer = FactorICAnalyzer(ry_data, price_data)
    analyzer.print_analysis_report()
    
    # 导出结果
    os.makedirs(config['output_dir'], exist_ok=True)
    analyzer.export_results(config['output_dir'])
    
    return analyzer


def run_all(config: dict):
    """运行全部分析"""
    print("\n" + "=" * 80)
    print(f"  沪镍展期收益率因子完整分析")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # 1. 实时表格
    print("\n" + "=" * 80)
    print("  [1/4] 实时展期收益率表格")
    print("=" * 80)
    try:
        run_realtime(config)
    except Exception as e:
        print(f"  跳过实时数据（需要同花顺API）: {e}")
    
    # 2. 历史数据
    print("\n" + "=" * 80)
    print("  [2/4] 历史展期收益率计算")
    print("=" * 80)
    ry_data, contracts_data = run_history(config)
    
    # 3. 阈值计算
    print("\n" + "=" * 80)
    print("  [3/4] 分位数阈值计算")
    print("=" * 80)
    run_threshold(config, ry_data)
    
    # 4. IC分析
    print("\n" + "=" * 80)
    print("  [4/4] 因子IC分析")
    print("=" * 80)
    run_ic_analysis(config, ry_data, contracts_data)
    
    # 汇总
    print("\n" + "=" * 80)
    print("  分析完成！")
    print("=" * 80)
    print(f"\n  输出文件位置: {config['output_dir']}/")
    print(f"  - ni_roll_yield_weighted_avg.csv  历史展期收益率")
    print(f"  - ic_summary.csv                  IC统计汇总")
    print(f"  - group_returns.csv               分组收益分析")
    print(f"  - factor_returns.csv              因子与收益率数据")
    print("=" * 80 + "\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='沪镍展期收益率因子分析')
    parser.add_argument(
        'mode',
        nargs='?',
        default='all',
        choices=['realtime', 'history', 'threshold', 'ic', 'all'],
        help='运行模式'
    )
    
    args = parser.parse_args()
    
    if args.mode == 'realtime':
        run_realtime(CONFIG)
    elif args.mode == 'history':
        run_history(CONFIG)
    elif args.mode == 'threshold':
        ry_data, _ = run_history(CONFIG)
        run_threshold(CONFIG, ry_data)
    elif args.mode == 'ic':
        ry_data, contracts_data = run_history(CONFIG)
        run_ic_analysis(CONFIG, ry_data, contracts_data)
    else:
        run_all(CONFIG)


if __name__ == '__main__':
    main()

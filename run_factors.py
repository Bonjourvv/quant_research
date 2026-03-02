#!/usr/bin/env python3
"""
展期收益率因子监控

运行: python3 run_factors.py
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.factors.roll_yield import RollYieldFactor


def main():
    print('\n' + '=' * 70)
    print(f'  展期收益率因子（持仓量筛选版）  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 70)

    factor = RollYieldFactor()

    for product, name in [('ni', '沪镍'), ('ss', '不锈钢')]:
        result = factor.fetch_roll_yield(product)

        print(f'\n  【{name}】')

        if 'error' in result:
            print(f'    ⚠️  {result["error"]}')
            continue

        # 信号emoji
        signal_emoji = {'bullish': '🟢', 'bearish': '🔴', 'neutral': '⚪'}
        structure_emoji = '📈' if result['structure'] == 'contango' else '📉'

        # 格式化持仓量
        near_oi = result.get('near_oi', 0)
        far_oi = result.get('far_oi', 0)
        
        print(f'    主力   {result["near_contract"].split(".")[0]}: {result["near_price"]:>10,.0f}  '
              f'(剩余{result["near_days"]:>3}天, OI: {near_oi:>8,.0f})')
        print(f'    次主力 {result["far_contract"].split(".")[0]}: {result["far_price"]:>10,.0f}  '
              f'(剩余{result["far_days"]:>3}天, OI: {far_oi:>8,.0f})')
        print(f'    期限结构: {structure_emoji} {result["structure"]}')
        print(f'    展期收益率: {result["roll_yield"] * 100:>6.2f}% (年化)')
        print(f'    信号: {signal_emoji[result["signal"]]} {result["signal"]}')

    print('\n' + '-' * 70)
    print('  解读:')
    print('     contango (升水): 远月>近月, 做多有展期损失')
    print('     backwardation (贴水): 远月<近月, 做多有展期收益')
    print('     bearish: 升水>5%, 不利做多')
    print('     bullish: 贴水>5%, 有利做多')
    print('-' * 70)
    print('  合约选择逻辑:')
    print('     主力 = 持仓量最大的合约')
    print('     次主力 = 持仓量第二大的合约')
    print('     换月时市场资金自动迁移，无需手动调整')
    print('=' * 70 + '\n')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
展期收益率因子监控

运行: python3 run_factors.py
"""

import requests
import json
import math
import os
from datetime import date, datetime


def load_token():
    """加载access_token"""
    cache_file = os.path.join(os.path.dirname(__file__), 'config', '.token_cache.json')
    with open(cache_file) as f:
        return json.load(f)['access_token']


def get_latest_close(token, code):
    """获取合约最新收盘价"""
    url = 'https://quantapi.51ifind.com/api/v1/cmd_history_quotation'
    headers = {'Content-Type': 'application/json', 'access_token': token}
    
    params = {
        'codes': code,
        'indicators': 'close',
        'startdate': '20260201',
        'enddate': '20260224',
        'period': 'D'
    }
    
    resp = requests.post(url, json=params, headers=headers, timeout=10)
    data = resp.json()
    
    if data.get('errorcode') != 0:
        return None
        
    tables = data.get('tables', [])
    if not tables:
        return None
        
    closes = tables[0].get('table', {}).get('close', [])
    return closes[-1] if closes else None


def calculate_roll_yield(near_price, far_price, near_days, far_days):
    """计算展期收益率"""
    if near_price <= 0 or far_price <= 0 or far_days <= near_days:
        return 0
    return (math.log(far_price) - math.log(near_price)) * 365 / (far_days - near_days)


def get_signal(roll_yield):
    """根据展期收益率生成信号"""
    if roll_yield > 0.05:
        return 'bearish', '🔴'
    elif roll_yield < -0.05:
        return 'bullish', '🟢'
    else:
        return 'neutral', '⚪'


def analyze_product(token, product, name):
    """分析单个品种的展期收益率"""
    today = date.today()
    
    # 确定近月和远月合约
    if today.month <= 2:
        near_month = f'{product}2603.SHF'
        far_month = f'{product}2604.SHF'
        near_expiry = date(2026, 3, 15)
        far_expiry = date(2026, 4, 15)
    else:
        # 动态计算（简化版）
        near_m = today.month + 1
        far_m = today.month + 2
        near_y = today.year
        far_y = today.year
        if near_m > 12:
            near_m -= 12
            near_y += 1
        if far_m > 12:
            far_m -= 12
            far_y += 1
        near_month = f'{product}{str(near_y)[-2:]}{near_m:02d}.SHF'
        far_month = f'{product}{str(far_y)[-2:]}{far_m:02d}.SHF'
        near_expiry = date(near_y, near_m, 15)
        far_expiry = date(far_y, far_m, 15)
    
    # 获取价格
    near_price = get_latest_close(token, near_month)
    far_price = get_latest_close(token, far_month)
    
    if near_price is None or far_price is None:
        print(f'\n  【{name}】')
        print(f'    ⚠️  数据获取失败')
        return
    
    # 计算
    near_days = (near_expiry - today).days
    far_days = (far_expiry - today).days
    roll_yield = calculate_roll_yield(near_price, far_price, near_days, far_days)
    structure = 'contango' if far_price > near_price else 'backwardation'
    signal, emoji = get_signal(roll_yield)
    
    # 输出
    print(f'\n  【{name}】')
    print(f'    近月 {near_month.split(".")[0]}: {near_price:>10,.0f}  (剩余{near_days}天)')
    print(f'    远月 {far_month.split(".")[0]}: {far_price:>10,.0f}  (剩余{far_days}天)')
    print(f'    期限结构: {"📈" if structure == "contango" else "📉"} {structure}')
    print(f'    展期收益率: {roll_yield*100:>6.2f}% (年化)')
    print(f'    信号: {emoji} {signal}')


def main():
    print('\n' + '=' * 60)
    print(f'  📊 展期收益率因子  |  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)
    
    try:
        token = load_token()
    except Exception as e:
        print(f'\n  ❌ 无法加载token: {e}')
        print('  请确保已配置好 config/.token_cache.json')
        return
    
    analyze_product(token, 'ni', '沪镍')
    analyze_product(token, 'ss', '不锈钢')
    
    print('\n' + '-' * 60)
    print('  📖 解读:')
    print('     contango (升水): 远月>近月, 做多有展期损失')
    print('     backwardation (贴水): 远月<近月, 做多有展期收益')
    print('     bearish: 升水>5%, 不利做多')
    print('     bullish: 贴水>5%, 有利做多')
    print('=' * 60 + '\n')


if __name__ == '__main__':
    main()

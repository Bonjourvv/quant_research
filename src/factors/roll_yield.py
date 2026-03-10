"""
展期收益率因子 (Roll Yield Factor)

功能：
1. 实时计算：获取当前所有相邻合约对的展期收益率，汇总成表格
2. 历史计算：滚动计算历史每日的展期收益率序列
3. 多种汇总方式：加权平均、中位数、主力次主力、全曲线拟合

公式：
    展期收益率 = [ln(远月价格) - ln(近月价格)] × 365 / (远月剩余天数 - 近月剩余天数)

含义：
    - 正值（远月升水/contango）：持有多头会有展期损失
    - 负值（远月贴水/backwardation）：持有多头会有展期收益
"""

import math
import pandas as pd
import numpy as np
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional
import os
import sys

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class RollYieldFactor:
    """展期收益率因子计算器"""
    
    def __init__(self, ths_client=None, tushare_client=None):
        """
        初始化
        
        Args:
            ths_client: 同花顺API客户端（实时数据）
            tushare_client: Tushare客户端（历史数据）
        """
        self.ths_client = ths_client
        self.ts_client = tushare_client
        
    def _get_ths_client(self):
        """懒加载同花顺客户端"""
        if self.ths_client is None:
            from src.data_fetcher.ths_client import THSClient
            self.ths_client = THSClient()
        return self.ths_client
    
    def _get_ts_client(self):
        """懒加载Tushare客户端"""
        if self.ts_client is None:
            from src.data_fetcher.tushare_client import TushareClient
            self.ts_client = TushareClient()
        return self.ts_client
    
    # ========================================================
    # 基础计算方法
    # ========================================================
    
    @staticmethod
    def get_contract_expiry(contract_code: str) -> date:
        """根据合约代码获取到期日"""
        code = contract_code.split('.')[0].upper()
        year_month = ''.join(c for c in code if c.isdigit())
        
        year = 2000 + int(year_month[:2])
        month = int(year_month[2:])
        
        return date(year, month, 15)
    
    @staticmethod
    def days_to_expiry(contract_code: str, current_date: date = None) -> int:
        """计算合约剩余天数"""
        if current_date is None:
            current_date = date.today()
        expiry = RollYieldFactor.get_contract_expiry(contract_code)
        return (expiry - current_date).days
    
    @staticmethod
    def calc_roll_yield(
            near_price: float,
            far_price: float,
            near_days: int,
            far_days: int
    ) -> float:
        """计算单对合约的展期收益率（年化）"""
        if near_price <= 0 or far_price <= 0:
            return np.nan
        
        day_diff = far_days - near_days
        if day_diff <= 0:
            return np.nan
        
        return (math.log(far_price) - math.log(near_price)) * 365 / day_diff

    # ========================================================
    # 实时计算：当前所有合约对的展期收益率
    # ========================================================
    
    def get_contracts_by_oi(self, product: str = 'ni', min_oi: int = 1000) -> List[Dict]:
        """
        按持仓量筛选活跃合约（实时）
        
        Returns:
            [{'code': 'NI2505.SHF', 'oi': 85000, 'days': 45, 'price': 128000}, ...]
        """
        today = date.today()
        client = self._get_ths_client()
        
        contracts_with_oi = []
        
        for i in range(12):
            year = today.year
            month = today.month + i
            
            while month > 12:
                month -= 12
                year += 1
            
            code = f"{product.upper()}{str(year)[-2:]}{month:02d}.SHF"
            days = self.days_to_expiry(code, today)
            
            if days <= 0:
                continue
            
            try:
                quote = client.get_realtime_quote(code)
                if not quote:
                    continue
                
                oi = float(quote.get('openInterest', 0))
                price = float(quote.get('latest', 0))
                
                if oi >= min_oi and price > 0:
                    contracts_with_oi.append({
                        'code': code,
                        'contract': code.split('.')[0],
                        'price': price,
                        'oi': oi,
                        'days': days,
                        'expiry_date': self.get_contract_expiry(code).strftime('%Y-%m-%d')
                    })
            except Exception:
                continue
        
        contracts_with_oi.sort(key=lambda x: x['oi'], reverse=True)
        return contracts_with_oi

    def get_realtime_roll_yield_table(
            self,
            product: str = 'ni',
            min_oi: int = 1000
    ) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
        """
        获取当前所有相邻合约对的展期收益率汇总表
        
        Returns:
            (合约表, 合约对展期收益率表, 汇总统计)
        """
        contracts = self.get_contracts_by_oi(product, min_oi)
        contracts_df = pd.DataFrame(contracts)
        
        if len(contracts_df) < 2:
            return contracts_df, pd.DataFrame(), {}
        
        # 按到期日排序
        contracts_df = contracts_df.sort_values('days').reset_index(drop=True)
        
        # 计算相邻合约对的展期收益率
        pairs = []
        for i in range(len(contracts_df) - 1):
            near = contracts_df.iloc[i]
            far = contracts_df.iloc[i + 1]
            
            ry = self.calc_roll_yield(
                near['price'], far['price'],
                near['days'], far['days']
            )
            
            spread = far['price'] - near['price']
            weight = min(near['oi'], far['oi'])
            
            pairs.append({
                'near': near['contract'],
                'far': far['contract'],
                'pair': f"{near['contract']}-{far['contract']}",
                'near_price': near['price'],
                'far_price': far['price'],
                'spread': spread,
                'spread_pct': spread / near['price'] * 100,
                'day_diff': far['days'] - near['days'],
                'roll_yield': ry,
                'roll_yield_pct': ry * 100 if not np.isnan(ry) else np.nan,
                'weight': weight,
                'structure': 'contango' if spread > 0 else 'backwardation'
            })
        
        pairs_df = pd.DataFrame(pairs)
        
        # 汇总统计
        valid_ry = pairs_df['roll_yield'].dropna()
        weights = pairs_df.loc[valid_ry.index, 'weight']
        
        # 主力-次主力展期收益率
        top2 = contracts_df.nlargest(2, 'oi').sort_values('days')
        dominant_ry = self.calc_roll_yield(
            top2.iloc[0]['price'], top2.iloc[1]['price'],
            top2.iloc[0]['days'], top2.iloc[1]['days']
        ) if len(top2) >= 2 else np.nan
        
        summary = {
            'product': product.upper(),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'contracts_count': len(contracts_df),
            'pairs_count': len(pairs_df),
            'weighted_avg': np.average(valid_ry, weights=weights) if len(valid_ry) > 0 else np.nan,
            'simple_avg': valid_ry.mean(),
            'median': valid_ry.median(),
            'min': valid_ry.min(),
            'max': valid_ry.max(),
            'dominant_ry': dominant_ry,
            'structure': 'contango' if pairs_df['spread'].sum() > 0 else 'backwardation'
        }
        
        return contracts_df, pairs_df, summary
    
    def print_realtime_table(self, product: str = 'ni'):
        """打印实时展期收益率表格"""
        contracts_df, pairs_df, summary = self.get_realtime_roll_yield_table(product)
        
        product_name = {'ni': '沪镍', 'ss': '不锈钢'}.get(product.lower(), product.upper())
        
        print("\n" + "=" * 80)
        print(f"  {product_name} 展期收益率分析  |  {summary.get('timestamp', '')}")
        print("=" * 80)
        
        # 合约行情表
        print("\n【活跃合约行情】")
        if contracts_df.empty:
            print("  无数据")
        else:
            print(f"  {'合约':<10} {'价格':>12} {'持仓量':>12} {'剩余天数':>10} {'到期日':>12}")
            print("  " + "-" * 58)
            for _, row in contracts_df.iterrows():
                marker = " ★" if row['oi'] == contracts_df['oi'].max() else ""
                print(f"  {row['contract']:<10} {row['price']:>12,.0f} {row['oi']:>12,.0f} "
                      f"{row['days']:>10} {row['expiry_date']:>12}{marker}")
            print("  " + "-" * 58)
            print("  ★ 主力合约（持仓量最大）")
        
        # 合约对展期收益率表
        print("\n【相邻合约对展期收益率】")
        if pairs_df.empty:
            print("  无数据")
        else:
            print(f"  {'合约对':<20} {'价差':>10} {'天数差':>8} {'年化展期收益率':>14} {'结构':>14}")
            print("  " + "-" * 70)
            for _, row in pairs_df.iterrows():
                ry_str = f"{row['roll_yield_pct']:>+.2f}%" if not np.isnan(row['roll_yield_pct']) else "N/A"
                struct_emoji = "📈" if row['structure'] == 'contango' else "📉"
                print(f"  {row['pair']:<20} {row['spread']:>+10,.0f} {row['day_diff']:>8} "
                      f"{ry_str:>14} {struct_emoji} {row['structure']:>10}")
        
        # 汇总统计
        print("\n【汇总统计】")
        print(f"  持仓量加权平均:  {summary['weighted_avg']*100:>+8.2f}%")
        print(f"  简单平均:        {summary['simple_avg']*100:>+8.2f}%")
        print(f"  中位数:          {summary['median']*100:>+8.2f}%")
        print(f"  主力-次主力:     {summary['dominant_ry']*100:>+8.2f}%")
        print(f"  期限结构:        {summary['structure']}")
        
        # 信号
        ry = summary['weighted_avg']
        if ry < -0.05:
            signal = "🟢 bullish (贴水深，利于做多)"
        elif ry > 0.05:
            signal = "🔴 bearish (升水深，利于做空)"
        else:
            signal = "⚪ neutral"
        print(f"  交易信号:        {signal}")
        
        print("=" * 80 + "\n")
        
        return contracts_df, pairs_df, summary
    
    def fetch_roll_yield(self, product: str = 'ni') -> Dict:
        """
        获取品种的展期收益率（兼容旧接口）
        
        Returns:
            包含展期收益率信息的字典
        """
        _, _, summary = self.get_realtime_roll_yield_table(product)
        
        if not summary:
            return {'product': product, 'error': '数据获取失败'}
        
        ry = summary['weighted_avg']
        
        # 信号判断
        if ry < -0.05:
            signal = 'bullish'
        elif ry > 0.05:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return {
            'product': product,
            'roll_yield': ry,
            'roll_yield_pct': f"{ry * 100:.2f}%",
            'structure': summary['structure'],
            'signal': signal,
            'timestamp': summary['timestamp']
        }


# ============================================================
# 历史展期收益率计算
# ============================================================

class RollYieldHistory:
    """历史展期收益率计算器"""
    
    def __init__(self, tushare_client=None):
        self.ts_client = tushare_client
        self._data_cache = None
        
    def _get_client(self):
        if self.ts_client is None:
            from src.data_fetcher.tushare_client import TushareClient
            self.ts_client = TushareClient()
        return self.ts_client
    
    @staticmethod
    def get_contract_expiry_days(ts_code: str, trade_date: str) -> int:
        """计算合约剩余天数"""
        code = ts_code.split('.')[0].upper()
        year_month = ''.join(c for c in code if c.isdigit())
        
        year = 2000 + int(year_month[:2])
        month = int(year_month[2:])
        expiry = date(year, month, 15)
        
        trade_dt = datetime.strptime(trade_date, '%Y%m%d').date()
        return (expiry - trade_dt).days
    
    @staticmethod
    def calc_roll_yield(near_price, far_price, near_days, far_days) -> float:
        if near_price <= 0 or far_price <= 0:
            return np.nan
        day_diff = far_days - near_days
        if day_diff <= 0:
            return np.nan
        return (math.log(far_price) - math.log(near_price)) * 365 / day_diff
    
    def load_all_contracts_data(
            self,
            product: str = 'NI',
            start_date: str = '20150401',
            end_date: str = None,
            cache_file: str = None
    ) -> pd.DataFrame:
        """加载所有合约历史数据"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        if cache_file and os.path.exists(cache_file):
            print(f"从缓存加载: {cache_file}")
            self._data_cache = pd.read_csv(cache_file, dtype={'trade_date': str})
            return self._data_cache
        
        print(f"从Tushare获取 {product} 数据 ({start_date} ~ {end_date})...")
        client = self._get_client()
        df = client.get_all_contracts_daily(product, start_date, end_date)
        
        if cache_file and not df.empty:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            df.to_csv(cache_file, index=False)
            print(f"已缓存到: {cache_file}")
        
        self._data_cache = df
        return df
    
    def calc_daily_roll_yield_table(
            self,
            daily_data: pd.DataFrame,
            trade_date: str,
            min_oi: int = 1000
    ) -> Tuple[pd.DataFrame, Dict]:
        """计算单日所有合约对的展期收益率表格"""
        df = daily_data[daily_data['oi'] >= min_oi].copy()
        
        if len(df) < 2:
            return pd.DataFrame(), {'trade_date': trade_date, 'roll_yield': np.nan}
        
        df['days_to_expiry'] = df['ts_code'].apply(
            lambda x: self.get_contract_expiry_days(x, trade_date)
        )
        df = df[df['days_to_expiry'] > 0].sort_values('days_to_expiry')
        
        if len(df) < 2:
            return pd.DataFrame(), {'trade_date': trade_date, 'roll_yield': np.nan}
        
        # 计算相邻合约对
        pairs = []
        for i in range(len(df) - 1):
            near = df.iloc[i]
            far = df.iloc[i + 1]
            
            ry = self.calc_roll_yield(
                near['close'], far['close'],
                near['days_to_expiry'], far['days_to_expiry']
            )
            
            if not np.isnan(ry):
                pairs.append({
                    'trade_date': trade_date,
                    'near': near['ts_code'],
                    'far': far['ts_code'],
                    'near_price': near['close'],
                    'far_price': far['close'],
                    'spread': far['close'] - near['close'],
                    'day_diff': far['days_to_expiry'] - near['days_to_expiry'],
                    'roll_yield': ry,
                    'weight': min(near['oi'], far['oi'])
                })
        
        pairs_df = pd.DataFrame(pairs)
        
        if pairs_df.empty:
            return pairs_df, {'trade_date': trade_date, 'roll_yield': np.nan}
        
        # 汇总
        weights = pairs_df['weight'].values
        ry_values = pairs_df['roll_yield'].values
        
        summary = {
            'trade_date': trade_date,
            'pairs_count': len(pairs_df),
            'weighted_avg': np.average(ry_values, weights=weights),
            'simple_avg': np.mean(ry_values),
            'median': np.median(ry_values),
            'structure': 'contango' if pairs_df['spread'].sum() > 0 else 'backwardation'
        }
        
        return pairs_df, summary
    
    def calc_history_roll_yield(
            self,
            data: pd.DataFrame = None,
            method: str = 'weighted_avg',
            min_oi: int = 1000
    ) -> pd.DataFrame:
        """计算历史所有交易日的展期收益率"""
        if data is None:
            data = self._data_cache
        
        if data is None or data.empty:
            raise ValueError("没有数据")
        
        trade_dates = sorted(data['trade_date'].unique())
        results = []
        total = len(trade_dates)
        
        print(f"计算 {total} 个交易日的展期收益率...")
        
        for idx, td in enumerate(trade_dates):
            if (idx + 1) % 100 == 0:
                print(f"  进度: {idx + 1}/{total}")
            
            daily_data = data[data['trade_date'] == td]
            _, summary = self.calc_daily_roll_yield_table(daily_data, td, min_oi)
            
            results.append({
                'trade_date': summary['trade_date'],
                'roll_yield': summary.get(method, summary.get('weighted_avg', np.nan)),
                'pairs_count': summary.get('pairs_count', 0),
                'structure': summary.get('structure', 'unknown')
            })
        
        result_df = pd.DataFrame(results)
        result_df['trade_date'] = pd.to_datetime(result_df['trade_date'])
        result_df = result_df.sort_values('trade_date')
        
        print(f"完成！共 {len(result_df)} 条记录")
        
        return result_df


def main():
    """测试展期收益率因子"""
    print("=" * 60)
    print("展期收益率因子测试")
    print("=" * 60)
    
    factor = RollYieldFactor()
    
    for product in ['ni', 'ss']:
        factor.print_realtime_table(product)


if __name__ == '__main__':
    main()

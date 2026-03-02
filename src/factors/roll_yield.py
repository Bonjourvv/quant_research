"""
展期收益率因子 (Roll Yield Factor)

公式：
    展期收益率 = [ln(远月价格) - ln(近月价格)] × 365 / (远月剩余天数 - 近月剩余天数)

含义：
    - 正值（远月升水/contango）：持有多头会有展期损失
    - 负值（远月贴水/backwardation）：持有多头会有展期收益
    
策略逻辑（基于银河期货研报）：
    - 做多展期收益率高的品种（贴水深）
    - 做空展期收益率低的品种（升水深）

修改记录：
    - 2026-03-02: 改用持仓量筛选主力/次主力合约，替代硬编码月份
"""

import math
from datetime import datetime, date
from typing import Optional, Dict, Tuple, List
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class RollYieldFactor:
    """展期收益率因子计算器"""
    
    def __init__(self, ths_client=None):
        """
        初始化
        
        Args:
            ths_client: 同花顺API客户端实例，如果为None则会自动创建
        """
        self.ths_client = ths_client
        
    def _get_client(self):
        """懒加载获取API客户端"""
        if self.ths_client is None:
            from src.data_fetcher.ths_client import THSClient
            self.ths_client = THSClient()
        return self.ths_client
    
    @staticmethod
    def get_contract_expiry(contract_code: str) -> date:
        """
        根据合约代码获取到期日
        
        Args:
            contract_code: 如 'NI2503.SHF'
            
        Returns:
            到期日（合约月份的第15个交易日，简化为15号）
        """
        # 提取年月：NI2503.SHF -> 2503
        code = contract_code.split('.')[0].upper()  # NI2503
        
        # 提取数字部分
        year_month = ''
        for char in code:
            if char.isdigit():
                year_month += char
        
        year = 2000 + int(year_month[:2])  # 25 -> 2025
        month = int(year_month[2:])  # 03 -> 3
        
        # 期货合约一般在合约月份的15日左右到期（简化处理）
        return date(year, month, 15)
    
    @staticmethod
    def days_to_expiry(contract_code: str, current_date: date = None) -> int:
        """
        计算合约剩余天数
        
        Args:
            contract_code: 合约代码
            current_date: 当前日期，默认为今天
            
        Returns:
            剩余天数
        """
        if current_date is None:
            current_date = date.today()
            
        expiry = RollYieldFactor.get_contract_expiry(contract_code)
        return (expiry - current_date).days
    
    @staticmethod
    def calculate(
        near_price: float,
        far_price: float,
        near_days: int,
        far_days: int
    ) -> float:
        """
        计算展期收益率
        
        Args:
            near_price: 近月合约价格
            far_price: 远月合约价格
            near_days: 近月合约剩余天数
            far_days: 远月合约剩余天数
            
        Returns:
            年化展期收益率
        """
        if near_price <= 0 or far_price <= 0:
            return 0.0
            
        day_diff = far_days - near_days
        if day_diff <= 0:
            return 0.0
            
        # 公式：[ln(远月) - ln(近月)] × 365 / 天数差
        roll_yield = (math.log(far_price) - math.log(near_price)) * 365 / day_diff
        
        return roll_yield

    def get_contracts_by_oi(self, product: str = 'ni', min_oi: int = 1000) -> List[Dict]:
        """
        按持仓量筛选活跃合约
        
        Args:
            product: 品种代码，'ni'=沪镍, 'ss'=不锈钢
            min_oi: 最小持仓量阈值
            
        Returns:
            合约列表，按持仓量降序排列
            [{'code': 'NI2505.SHF', 'oi': 85000, 'days': 45, 'price': 128000}, ...]
        """
        today = date.today()
        client = self._get_client()
        
        contracts_with_oi = []
        
        # 遍历未来12个月的合约（1-12月全覆盖）
        for i in range(12):
            year = today.year
            month = today.month + i
            
            while month > 12:
                month -= 12
                year += 1
            
            code = f"{product.upper()}{str(year)[-2:]}{month:02d}.SHF"
            
            # 跳过已到期合约
            days_left = self.days_to_expiry(code, today)
            if days_left <= 0:
                continue
            
            # 获取行情数据（含持仓量）
            try:
                quote = client.get_realtime_quote(code)
                if not quote:
                    continue
                    
                oi = float(quote.get('openInterest', 0))
                price = float(quote.get('latest', 0))
                
                if oi >= min_oi and price > 0:
                    contracts_with_oi.append({
                        'code': code,
                        'oi': oi,
                        'days': days_left,
                        'price': price
                    })
            except Exception as e:
                # 合约可能不存在或无数据，跳过
                continue
        
        # 按持仓量降序排列
        contracts_with_oi.sort(key=lambda x: x['oi'], reverse=True)
        
        return contracts_with_oi

    def get_dominant_contracts(self, product: str = 'ni') -> Tuple[str, str]:
        """
        获取主力和次主力合约（按持仓量排序）
        
        主力合约：持仓量最大的合约
        次主力合约：持仓量第二大的合约
        
        Args:
            product: 品种代码
            
        Returns:
            (近月合约, 远月合约) - 按到期日排序，近月在前
        """
        contracts = self.get_contracts_by_oi(product)
        
        if len(contracts) < 2:
            codes = [c['code'] for c in contracts]
            raise ValueError(f"活跃合约不足2个: {codes}")
        
        # 取持仓量前两名
        top2 = contracts[:2]
        
        # 按到期日排序（近月在前）
        top2.sort(key=lambda x: x['days'])
        
        return top2[0]['code'], top2[1]['code']

    def fetch_contract_price(self, contract_code: str) -> Optional[float]:
        """
        获取合约的最新价格
        
        Args:
            contract_code: 合约代码
            
        Returns:
            最新价格，获取失败返回None
        """
        client = self._get_client()
        
        try:
            data = client.get_realtime_quote(contract_code)
            if data and 'latest' in data:
                return float(data['latest'])
        except Exception as e:
            print(f"获取{contract_code}价格失败: {e}")
            
        return None
    
    def fetch_roll_yield(self, product: str = 'ni') -> Dict:
        """
        获取品种的展期收益率
        
        使用主力合约和次主力合约计算，反映实际换月成本
        
        Args:
            product: 品种代码，'ni'=沪镍, 'ss'=不锈钢
            
        Returns:
            {
                'product': 品种代码,
                'near_contract': 主力合约（近月）,
                'far_contract': 次主力合约（远月）,
                'near_price': 近月价格,
                'far_price': 远月价格,
                'near_days': 近月剩余天数,
                'far_days': 远月剩余天数,
                'near_oi': 近月持仓量,
                'far_oi': 远月持仓量,
                'roll_yield': 展期收益率（年化）,
                'roll_yield_pct': 展期收益率（百分比字符串）,
                'structure': 'contango'/'backwardation',
                'signal': 'bullish'/'bearish'/'neutral',
                'timestamp': 时间戳
            }
        """
        today = date.today()
        
        # 获取主力和次主力合约（按持仓量）
        try:
            contracts = self.get_contracts_by_oi(product)
            
            if len(contracts) < 2:
                return {
                    'product': product,
                    'error': f'活跃合约不足，仅找到{len(contracts)}个',
                    'timestamp': datetime.now().isoformat()
                }
            
            # 取持仓量前两名，按到期日排序
            top2 = sorted(contracts[:2], key=lambda x: x['days'])
            
            near = top2[0]  # 近月（到期日更近）
            far = top2[1]   # 远月（到期日更远）
            
        except Exception as e:
            return {
                'product': product,
                'error': f'获取合约失败: {e}',
                'timestamp': datetime.now().isoformat()
            }
        
        near_contract = near['code']
        far_contract = far['code']
        near_price = near['price']
        far_price = far['price']
        near_days = near['days']
        far_days = far['days']
        near_oi = near['oi']
        far_oi = far['oi']
        
        # 计算展期收益率
        roll_yield = self.calculate(near_price, far_price, near_days, far_days)
        
        # 判断期限结构
        if far_price > near_price:
            structure = 'contango'  # 远月升水（正常市场）
        else:
            structure = 'backwardation'  # 远月贴水（现货紧张）
            
        # 生成交易信号
        # 贴水（负展期收益率）= 做多有利 = bullish
        # 升水（正展期收益率）= 做多不利 = bearish
        if roll_yield < -0.05:  # 年化贴水超过5%
            signal = 'bullish'
        elif roll_yield > 0.05:  # 年化升水超过5%
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return {
            'product': product,
            'near_contract': near_contract,
            'far_contract': far_contract,
            'near_price': near_price,
            'far_price': far_price,
            'near_days': near_days,
            'far_days': far_days,
            'near_oi': near_oi,
            'far_oi': far_oi,
            'roll_yield': roll_yield,
            'roll_yield_pct': f"{roll_yield * 100:.2f}%",
            'structure': structure,
            'signal': signal,
            'timestamp': datetime.now().isoformat()
        }


def main():
    """测试展期收益率因子"""
    print("=" * 60)
    print("展期收益率因子测试（持仓量筛选版）")
    print("=" * 60)
    
    factor = RollYieldFactor()
    
    for product, name in [('ni', '沪镍'), ('ss', '不锈钢')]:
        print(f"\n【{name}】")
        
        # 先显示所有活跃合约
        print("  活跃合约（按持仓量排序）:")
        contracts = factor.get_contracts_by_oi(product)
        for i, c in enumerate(contracts[:4]):
            marker = "← 主力" if i == 0 else ("← 次主力" if i == 1 else "")
            print(f"    {c['code']}: OI={c['oi']:,.0f}, 剩余{c['days']}天 {marker}")
        
        # 计算展期收益率
        result = factor.fetch_roll_yield(product)
        
        if 'error' in result:
            print(f"  错误: {result['error']}")
            continue
        
        print(f"\n  展期收益率计算:")
        print(f"    近月(主力): {result['near_contract']} @ {result['near_price']:,.0f} (OI: {result['near_oi']:,.0f})")
        print(f"    远月(次主力): {result['far_contract']} @ {result['far_price']:,.0f} (OI: {result['far_oi']:,.0f})")
        print(f"    期限结构: {result['structure']}")
        print(f"    展期收益率: {result['roll_yield_pct']} (年化)")
        print(f"    交易信号: {result['signal']}")
    
    print("\n" + "=" * 60)
    print("说明:")
    print("  - 主力合约: 持仓量最大的合约")
    print("  - 次主力合约: 持仓量第二大的合约")
    print("  - 换月时持仓量自动反映市场变化，无需手动干预")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()

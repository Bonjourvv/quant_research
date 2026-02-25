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
"""

import math
from datetime import datetime, date
from typing import Optional, Dict, Tuple
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
            contract_code: 如 'ni2503.SHF'
            
        Returns:
            到期日（合约月份的第15个交易日，简化为15号）
        """
        # 提取年月：ni2503.SHF -> 2503
        code = contract_code.split('.')[0]  # ni2503
        year_month = code[-4:]  # 2503
        
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
    
    def get_active_contracts(self, product: str = 'ni') -> list:
        """
        获取当前活跃的合约列表
        
        Args:
            product: 品种代码，'ni'=沪镍, 'ss'=不锈钢
            
        Returns:
            合约代码列表，按到期日排序
        """
        # 生成未来12个月的合约代码
        today = date.today()
        contracts = []
        
        for i in range(12):
            # 计算月份
            year = today.year
            month = today.month + i
            
            if month > 12:
                month -= 12
                year += 1
                
            # 格式化合约代码
            code = f"{product}{str(year)[-2:]}{month:02d}.SHF"
            
            # 只保留还未到期的合约
            if self.days_to_expiry(code, today) > 0:
                contracts.append(code)
                
        return contracts[:6]  # 返回最近6个合约
    
    def get_near_far_contracts(self, product: str = 'ni') -> Tuple[str, str]:
        """
        获取近月和远月合约代码
        
        Args:
            product: 品种代码
            
        Returns:
            (近月合约, 远月合约)
        """
        contracts = self.get_active_contracts(product)
        
        if len(contracts) < 2:
            raise ValueError(f"活跃合约数量不足: {contracts}")
            
        return contracts[0], contracts[1]
    
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
        
        Args:
            product: 品种代码，'ni'=沪镍, 'ss'=不锈钢
            
        Returns:
            {
                'product': 品种代码,
                'near_contract': 近月合约,
                'far_contract': 远月合约,
                'near_price': 近月价格,
                'far_price': 远月价格,
                'near_days': 近月剩余天数,
                'far_days': 远月剩余天数,
                'roll_yield': 展期收益率（年化）,
                'roll_yield_pct': 展期收益率（百分比）,
                'structure': 'contango'/'backwardation',
                'signal': 'bullish'/'bearish'/'neutral',
                'timestamp': 时间戳
            }
        """
        today = date.today()
        
        # 获取近远月合约
        near_contract, far_contract = self.get_near_far_contracts(product)
        
        # 获取价格
        near_price = self.fetch_contract_price(near_contract)
        far_price = self.fetch_contract_price(far_contract)
        
        if near_price is None or far_price is None:
            return {
                'product': product,
                'error': '价格获取失败',
                'near_contract': near_contract,
                'far_contract': far_contract,
                'timestamp': datetime.now().isoformat()
            }
        
        # 计算剩余天数
        near_days = self.days_to_expiry(near_contract, today)
        far_days = self.days_to_expiry(far_contract, today)
        
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
            'roll_yield': roll_yield,
            'roll_yield_pct': f"{roll_yield * 100:.2f}%",
            'structure': structure,
            'signal': signal,
            'timestamp': datetime.now().isoformat()
        }


def main():
    """测试展期收益率因子"""
    print("=" * 60)
    print("展期收益率因子测试")
    print("=" * 60)
    
    factor = RollYieldFactor()
    
    # 测试沪镍
    print("\n【沪镍】")
    result = factor.fetch_roll_yield('ni')
    
    if 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"近月合约: {result['near_contract']} @ {result['near_price']}")
        print(f"远月合约: {result['far_contract']} @ {result['far_price']}")
        print(f"近月剩余: {result['near_days']}天")
        print(f"远月剩余: {result['far_days']}天")
        print(f"期限结构: {result['structure']}")
        print(f"展期收益率: {result['roll_yield_pct']} (年化)")
        print(f"交易信号: {result['signal']}")
    
    # 测试不锈钢
    print("\n【不锈钢】")
    result = factor.fetch_roll_yield('ss')
    
    if 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"近月合约: {result['near_contract']} @ {result['near_price']}")
        print(f"远月合约: {result['far_contract']} @ {result['far_price']}")
        print(f"近月剩余: {result['near_days']}天")
        print(f"远月剩余: {result['far_days']}天")
        print(f"期限结构: {result['structure']}")
        print(f"展期收益率: {result['roll_yield_pct']} (年化)")
        print(f"交易信号: {result['signal']}")


if __name__ == '__main__':
    main()

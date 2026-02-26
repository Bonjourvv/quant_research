"""
同花顺 iFinD HTTP API 客户端

API文档：https://quantapi.51ifind.com
"""

import requests
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

# 尝试从config导入，如果失败则使用默认值
try:
    from config.settings import REFRESH_TOKEN, API_BASE_URL
except ImportError:
    REFRESH_TOKEN = ""
    API_BASE_URL = "https://quantapi.51ifind.com/api/v1"


class THSClient:
    """同花顺HTTP API客户端"""
    
    def __init__(self, refresh_token: str = None):
        """
        初始化客户端
        
        Args:
            refresh_token: 刷新令牌，如果不传则从配置文件读取
        """
        self.refresh_token = refresh_token or REFRESH_TOKEN
        self.base_url = API_BASE_URL
        self.access_token = None
        self.token_expiry = None
        
        # token缓存文件
        self.token_cache_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'config', '.token_cache.json'
        )
        
        # 尝试加载缓存的token
        self._load_token_cache()
        
    def _load_token_cache(self):
        """从缓存文件加载token"""
        try:
            if os.path.exists(self.token_cache_file):
                with open(self.token_cache_file, 'r') as f:
                    cache = json.load(f)
                    if cache.get('expiry'):
                        expiry = datetime.fromisoformat(cache['expiry'])
                        if expiry > datetime.now():
                            self.access_token = cache.get('access_token')
                            self.token_expiry = expiry
        except Exception:
            pass
            
    def _save_token_cache(self):
        """保存token到缓存文件"""
        try:
            cache = {
                'access_token': self.access_token,
                'expiry': self.token_expiry.isoformat() if self.token_expiry else None
            }
            os.makedirs(os.path.dirname(self.token_cache_file), exist_ok=True)
            with open(self.token_cache_file, 'w') as f:
                json.dump(cache, f)
        except Exception:
            pass
    
    def _ensure_access_token(self):
        """确保有有效的access_token"""
        # 检查是否需要刷新
        if self.access_token and self.token_expiry:
            if datetime.now() < self.token_expiry - timedelta(hours=1):
                return
                
        # 获取新的access_token
        if not self.refresh_token:
            raise ValueError("请先配置 refresh_token (在 config/settings.py 中)")
            
        url = f"{self.base_url}/get_access_token"
        payload = {"refresh_token": self.refresh_token}
        
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        
        if result.get('errorcode') != 0:
            raise Exception(f"获取access_token失败: {result.get('errmsg', '未知错误')}")
            
        self.access_token = result['data']['access_token']
        # access_token有效期7天，但我们设为6天以留余量
        self.token_expiry = datetime.now() + timedelta(days=6)
        
        self._save_token_cache()

    def get_realtime_quote(self, codes: str) -> Dict:
        """获取实时行情"""
        codes = codes.upper()

        params = {
            "codes": codes,
            "indicators": "latest,open,high,low,preClose,volume,amount,openInterest"
        }

        self._ensure_access_token()

        url = f"{self.base_url}/real_time_quotation"
        headers = {
            "Content-Type": "application/json",
            "access_token": self.access_token
        }

        resp = requests.post(url, json=params, headers=headers, timeout=30)
        result = resp.json()

        if result.get('errorcode') != 0:
            raise Exception(f"API请求失败: {result.get('errmsg', '未知错误')}")

        tables = result.get('tables', [])
        if not tables:
            return {}

        # 解析返回数据
        table_data = tables[0].get('table', {})
        parsed = {}
        for key, value in table_data.items():
            if isinstance(value, list) and len(value) > 0:
                parsed[key] = value[0]
            else:
                parsed[key] = value

        return parsed  # 确保这里有return


    def get_history_quote(
            self,
            codes: str,
            start_date: str,
            end_date: str,
            period: str = 'D'
    ) -> List[Dict]:
        """获取历史行情"""
        self._ensure_access_token()

        codes = codes.upper()

        url = f"{self.base_url}/history_data"  # 改这里
        headers = {
            "Content-Type": "application/json",
            "access_token": self.access_token
        }

        params = {
            "reqBody": {  # 包一层reqBody
                "codes": codes,
                "indicators": "open,close,high,low,volume",
                "startdate": start_date.replace('-', ''),
                "enddate": end_date.replace('-', '')
            }
        }

        resp = requests.post(url, json=params, headers=headers, timeout=30)
        result = resp.json()
        print(f"DEBUG: {result}")  # 临时debug

        if result.get('errorcode') != 0:
            raise Exception(f"API请求失败: {result.get('errmsg', '未知错误')}")

        tables = result.get('tables', [])
        if not tables:
            return []

        # 解析返回数据
        table = tables[0]
        table_data = table.get('table', {})
        time_list = table.get('time', [])

        results = []
        for t_idx, time_val in enumerate(time_list):
            row = {'date': time_val}
            for indicator, values in table_data.items():
                if t_idx < len(values):
                    row[indicator] = values[t_idx]
            results.append(row)

        return results

    def get_high_frequency(
            self,
            codes: str,
            start_time: str,
            end_time: str,
            period: int = 1
    ) -> List[Dict]:
        """
        获取高频分钟数据

        Args:
            codes: 合约代码，如 'NI2603.SHF'
            start_time: 开始时间，格式 '2026-02-26 09:15:00'
            end_time: 结束时间，格式 '2026-02-26 15:15:00'
            period: 时间周期，1=1分钟, 5=5分钟等

        Returns:
            分钟级行情数据列表
        """
        self._ensure_access_token()

        codes = codes.upper()

        url = f"{self.base_url}/high_frequency"
        headers = {
            "Content-Type": "application/json",
            "access_token": self.access_token
        }

        params = {
            "codes": codes,
            "indicators": "open,high,low,close,volume",
            "starttime": start_time,
            "endtime": end_time,
            "functionpara": {
                "Fill": "Original",
                "period": period
            }
        }

        resp = requests.post(url, json=params, headers=headers, timeout=30)
        result = resp.json()
        print(f"DEBUG: {result}")

        if result.get('errorcode') != 0:
            raise Exception(f"API请求失败: {result.get('errmsg', '未知错误')}")

        tables = result.get('tables', [])
        if not tables:
            return []

        # 解析返回数据
        table = tables[0]
        table_data = table.get('table', {})
        time_list = table.get('time', [])

        results = []
        for t_idx, time_val in enumerate(time_list):
            row = {'time': time_val}
            for indicator, values in table_data.items():
                if t_idx < len(values):
                    row[indicator] = values[t_idx]
            results.append(row)

        return results

def main():
    """测试API连接"""
    print("测试同花顺API连接...")

    client = THSClient()

    test_codes = [
        "NIZL.SHF",  # 主力合约
        "NI2603.SHF",  # 3月合约
        "NI2605.SHF",  # 5月合约
        "SSZL.SHF",  # 不锈钢主力
    ]

    for code in test_codes:
        print(f"\n测试 {code}:")
        try:
            quote = client.get_realtime_quote(code)
            print(f"  成功: {quote}")
        except Exception as e:
            print(f"  失败: {e}")
if __name__ == '__main__':
    main()


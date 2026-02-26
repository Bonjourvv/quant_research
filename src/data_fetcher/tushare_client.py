"""
Tushare API 客户端

文档：https://tushare.pro/document/2
"""

import tushare as ts
import tushare.pro.client as client
import pandas as pd
from typing import Optional

# 设置API地址
client.DataApi._DataApi__http_url = "http://tushare.xyz"

# Token配置
TUSHARE_TOKEN = "34337c3d66d26a15e1dd412f8ebf5ab31096f3c02a3ad60c4dd978dc"


class TushareClient:
    """Tushare API客户端"""

    def __init__(self, token: str = None):
        self.token = token or TUSHARE_TOKEN
        self.pro = ts.pro_api(self.token)

    def get_futures_daily(
            self,
            ts_code: str,
            start_date: str,
            end_date: str
    ) -> pd.DataFrame:
        """
        获取期货日线行情

        Args:
            ts_code: 合约代码，如 'NI2603.SHF'
            start_date: 开始日期，格式 'YYYYMMDD'
            end_date: 结束日期，格式 'YYYYMMDD'

        Returns:
            DataFrame with columns: trade_date, open, high, low, close, vol, oi
        """
        df = self.pro.fut_daily(
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            fields="ts_code,trade_date,open,high,low,close,vol,oi"
        )
        return df

    def get_futures_mapping(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取主力/次主力合约映射

        Args:
            ts_code: 品种代码，如 'NI.SHF'
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame with mapping_ts_code (主力合约代码)
        """
        df = self.pro.fut_mapping(
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
        )
        return df


def main():
    """测试Tushare连接"""
    print("测试Tushare API连接...")

    client = TushareClient()

    # 测试期货日线
    print("\n沪镍主力合约日线（最近5天）:")
    df = client.get_futures_daily("NI2603.SHF", "20260220", "20260225")
    print(df)

    # 测试主力映射
    print("\n沪镍主力合约映射:")
    df = client.get_futures_mapping("NI.SHF", "20260101", "20260225")
    print(df.head())


if __name__ == '__main__':
    main()
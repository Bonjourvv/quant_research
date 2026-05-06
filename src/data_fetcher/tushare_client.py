"""
Tushare API 客户端（扩展版）

文档：https://tushare.pro/document/2

扩展功能：
- 获取品种所有合约列表
- 批量获取多合约日线数据
- 获取指定日期的所有活跃合约行情
"""

import tushare as ts
import tushare.pro.client as client
import pandas as pd
from typing import Optional, List
from datetime import datetime, timedelta
import time
from requests.exceptions import RequestException

try:
    from config.settings import PRODUCT_CONFIG, TUSHARE_BASE_URL, TUSHARE_TOKEN
except ImportError:
    TUSHARE_BASE_URL = "http://tushare.xyz"
    TUSHARE_TOKEN = ""
    PRODUCT_CONFIG = {
        "NI": {"name": "沪镍", "exchange": "SHFE"},
        "SS": {"name": "不锈钢", "exchange": "SHFE"},
        "CU": {"name": "沪铜", "exchange": "SHFE"},
    }

client.DataApi._DataApi__http_url = TUSHARE_BASE_URL


class TushareClient:
    """Tushare API客户端"""

    def __init__(self, token: str = None, timeout: int = 60, max_retries: int = 3):
        self.token = token or TUSHARE_TOKEN
        if not self.token:
            raise ValueError("请先设置 TUSHARE_TOKEN 环境变量或 .env 配置")
        self.timeout = timeout
        self.max_retries = max_retries
        self.pro = ts.pro_api(self.token, timeout=self.timeout)
        
        # 缓存
        self._contract_cache = {}
        self._daily_cache = {}

    def _query_with_retry(self, api_name: str, fields: str = "", **kwargs) -> pd.DataFrame:
        """对 Tushare 查询增加重试，减少临时超时导致的整体失败。"""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.pro.query(api_name, fields=fields, **kwargs)
            except (RequestException, TimeoutError, Exception) as exc:
                last_error = exc
                message = str(exc)

                # token 错误属于配置问题，重试没有意义，直接给出明确提示。
                if "token不对" in message or "token不正确" in message or "token" in message and "确认" in message:
                    raise ValueError(
                        "当前配置的 TUSHARE_TOKEN 无效，请更新项目根目录 .env 中的 TUSHARE_TOKEN 后重试。"
                    ) from exc

                if attempt == self.max_retries:
                    break
                wait_seconds = min(2 * attempt, 5)
                print(f"  Tushare 请求重试 {attempt}/{self.max_retries} 失败: {exc}，{wait_seconds}s 后重试...")
                time.sleep(wait_seconds)
        raise last_error

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
        df = self._query_with_retry(
            "fut_daily",
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            fields="ts_code,trade_date,open,high,low,close,vol,oi",
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
        df = self._query_with_retry(
            "fut_mapping",
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
        )
        return df

    def get_futures_basic(self, exchange: str = 'SHFE') -> pd.DataFrame:
        """
        获取期货合约基础信息
        
        Args:
            exchange: 交易所代码，SHFE=上期所
            
        Returns:
            DataFrame with columns: ts_code, symbol, name, list_date, delist_date, etc.
        """
        df = self._query_with_retry(
            "fut_basic",
            exchange=exchange,
            fields="ts_code,symbol,name,fut_code,list_date,delist_date,multiplier",
        )
        return df

    def get_product_contracts(self, product: str, exchange: Optional[str] = None) -> pd.DataFrame:
        """
        获取指定品种所有合约列表
        
        Returns:
            DataFrame with columns: ts_code, list_date, delist_date
        """
        product = product.upper()
        product_meta = PRODUCT_CONFIG.get(product, {"exchange": exchange or "SHFE"})
        exchange = exchange or product_meta["exchange"]
        cache_key = f"{product.lower()}_contracts"
        if cache_key in self._contract_cache:
            return self._contract_cache[cache_key]
        
        df = self.get_futures_basic(exchange)
        
        # 筛选指定品种合约，排除主力连续合约
        product_df = df[
            (df['fut_code'] == product) &
            (~df['ts_code'].str.contains('L'))
        ].copy()
        
        product_df = product_df.sort_values('delist_date')
        
        self._contract_cache[cache_key] = product_df
        return product_df

    def get_ni_contracts(self) -> pd.DataFrame:
        """兼容旧接口：获取沪镍所有合约列表。"""
        return self.get_product_contracts("NI")

    def get_ss_contracts(self) -> pd.DataFrame:
        """获取不锈钢所有合约列表。"""
        return self.get_product_contracts("SS")

    def get_active_contracts_on_date(
            self, 
            trade_date: str, 
            product: str = 'NI'
    ) -> List[str]:
        """
        获取指定日期的活跃合约列表
        
        Args:
            trade_date: 交易日期，格式 'YYYYMMDD'
            product: 品种代码
            
        Returns:
            合约代码列表，按到期日排序
        """
        trade_date = trade_date.replace('-', '')
        
        product = product.upper()
        contracts_df = self.get_product_contracts(product)
        
        # 筛选在指定日期活跃的合约（已上市且未退市）
        active = contracts_df[
            (contracts_df['list_date'] <= trade_date) &
            (contracts_df['delist_date'] >= trade_date)
        ]
        
        # 按退市日期排序（即按到期日排序）
        active = active.sort_values('delist_date')
        
        return active['ts_code'].tolist()

    def get_all_contracts_daily(
            self,
            product: str,
            start_date: str,
            end_date: str,
            min_oi: int = 100
    ) -> pd.DataFrame:
        """
        获取品种所有合约在指定时间段的日线数据
        
        Args:
            product: 品种代码，如 'NI'
            start_date: 开始日期
            end_date: 结束日期
            min_oi: 最小持仓量过滤
            
        Returns:
            DataFrame with columns: trade_date, ts_code, close, oi, delist_date
        """
        start_date = start_date.replace('-', '')
        end_date = end_date.replace('-', '')
        
        product = product.upper()
        contracts_df = self.get_product_contracts(product)
        
        # 筛选在时间段内活跃的合约
        relevant_contracts = contracts_df[
            (contracts_df['delist_date'] >= start_date) &
            (contracts_df['list_date'] <= end_date)
        ]
        
        all_data = []
        total = len(relevant_contracts)
        
        for idx, (_, row) in enumerate(relevant_contracts.iterrows()):
            ts_code = row['ts_code']
            delist_date = row['delist_date']
            
            print(f"  获取 {ts_code} ({idx+1}/{total})...", end='')
            
            try:
                df = self.get_futures_daily(ts_code, start_date, end_date)
                
                if df is not None and not df.empty:
                    df['delist_date'] = delist_date
                    # 过滤低持仓量数据
                    df = df[df['oi'] >= min_oi]
                    all_data.append(df)
                    print(f" {len(df)}条")
                else:
                    print(" 无数据")
                    
            except Exception as e:
                print(f" 错误: {e}")
            
            # 避免API限频
            time.sleep(0.1)
        
        if not all_data:
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        result = result.sort_values(['trade_date', 'delist_date'])
        
        return result

    def update_all_contracts_daily(
            self,
            product: str,
            existing_data: pd.DataFrame,
            end_date: str,
            min_oi: int = 100
    ) -> pd.DataFrame:
        """
        基于现有缓存做增量更新。

        Args:
            product: 品种代码
            existing_data: 已有缓存数据
            end_date: 结束日期
            min_oi: 最小持仓量过滤

        Returns:
            更新后的完整数据
        """
        if existing_data is None or existing_data.empty:
            return self.get_all_contracts_daily(product, "20150401", end_date, min_oi)

        existing = existing_data.copy()
        existing["trade_date"] = existing["trade_date"].astype(str)

        last_trade_date = existing["trade_date"].max()
        target_end = end_date.replace("-", "")

        if last_trade_date >= target_end:
            return existing.sort_values(["trade_date", "delist_date"]).reset_index(drop=True)

        next_start = (datetime.strptime(last_trade_date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        increment = self.get_all_contracts_daily(product, next_start, target_end, min_oi)

        if increment is None or increment.empty:
            return existing.sort_values(["trade_date", "delist_date"]).reset_index(drop=True)

        merged = pd.concat([existing, increment], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        merged = merged.sort_values(["trade_date", "delist_date"]).reset_index(drop=True)
        return merged

    def get_latest_available_trade_date(
            self,
            ts_code: str,
            start_date: str,
            end_date: str,
    ) -> Optional[str]:
        """用历史行情接口探测某个合约当前最新可用交易日。"""
        df = self.get_futures_daily(ts_code, start_date, end_date)
        if df is None or df.empty:
            return None
        return str(df["trade_date"].astype(str).max())

    def get_dominant_daily(
            self,
            product: str,
            start_date: str,
            end_date: str
    ) -> pd.DataFrame:
        """
        获取主力合约日线数据（用于回测基准）
        
        Args:
            product: 品种代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame with columns: trade_date, dominant_code, close, oi
        """
        start_date = start_date.replace('-', '')
        end_date = end_date.replace('-', '')
        
        # 获取主力合约映射
        product = product.upper()
        exchange = PRODUCT_CONFIG.get(product, {}).get("exchange", "SHFE")
        mapping = self.get_futures_mapping(
            f"{product}.{exchange[:3]}",
            start_date,
            end_date
        )
        
        if mapping is None or mapping.empty:
            return pd.DataFrame()
        
        # 按日期获取主力合约价格
        results = []
        grouped = mapping.groupby('trade_date')
        
        for trade_date, group in grouped:
            dominant_code = group['mapping_ts_code'].iloc[0]
            
            # 获取该日主力合约行情
            daily = self.get_futures_daily(dominant_code, trade_date, trade_date)
            
            if daily is not None and not daily.empty:
                results.append({
                    'trade_date': trade_date,
                    'dominant_code': dominant_code,
                    'close': daily['close'].iloc[0],
                    'oi': daily['oi'].iloc[0]
                })
        
        return pd.DataFrame(results)


def main():
    """测试扩展功能"""
    print("测试Tushare API扩展功能...")
    print("=" * 60)

    ts_client = TushareClient()

    for product in ["NI", "SS"]:
        print(f"\n【{product} 合约列表】")
        contracts = ts_client.get_product_contracts(product)
        print(f"共 {len(contracts)} 个合约")
        print(contracts[['ts_code', 'list_date', 'delist_date']].head(10))

    # 测试获取指定日期活跃合约
    print("\n【2026-02-25 活跃合约】")
    active = ts_client.get_active_contracts_on_date('20260225', 'NI')
    print(active)

    # 测试获取主力映射
    print("\n【沪镍主力合约映射（最近5天）】")
    mapping = ts_client.get_futures_mapping("NI.SHF", "20260220", "20260225")
    print(mapping)


if __name__ == '__main__':
    main()

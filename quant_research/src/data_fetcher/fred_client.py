"""FRED 数据客户端。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from config.settings import FRED_API_KEY, RAW_DATA_DIR


class FredClient:
    """St. Louis Fed FRED API 客户端。"""

    base_url = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or FRED_API_KEY
        if not self.api_key:
            raise ValueError("请先设置 FRED_API_KEY 环境变量或 .env 配置")

    def get_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        cache: bool = True,
    ) -> pd.DataFrame:
        """获取单个 FRED 时间序列。"""
        value_col = series_id.lower()
        cache_path = RAW_DATA_DIR / "fred" / f"{value_col}.csv"
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date

        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            if cache_path.exists():
                cached = pd.read_csv(cache_path, parse_dates=["trade_date"])
                if start_date:
                    cached = cached[cached["trade_date"] >= pd.to_datetime(start_date)]
                if end_date:
                    cached = cached[cached["trade_date"] <= pd.to_datetime(end_date)]
                return cached.reset_index(drop=True)
            raise

        if "error_code" in payload:
            raise RuntimeError(f"FRED API 错误: {payload['error_code']} - {payload.get('error_message', '')}")

        observations = payload.get("observations", [])
        df = pd.DataFrame(observations)
        if df.empty:
            return df

        df = df.rename(columns={"date": "trade_date", "value": value_col})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df[value_col] = pd.to_numeric(df[value_col].replace(".", pd.NA), errors="coerce")
        df = df[["trade_date", value_col]].dropna().reset_index(drop=True)

        if cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, index=False)

        return df

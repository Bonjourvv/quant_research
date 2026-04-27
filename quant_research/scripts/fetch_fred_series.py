#!/usr/bin/env python3
"""从 FRED 拉取单个时间序列并保存为 CSV。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import requests


FRED_SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "fred"


def fetch_fred_series(
    series_id: str,
    api_key: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """拉取 FRED 序列观测值。"""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if start_date:
        params["observation_start"] = start_date
    if end_date:
        params["observation_end"] = end_date

    response = requests.get(FRED_SERIES_URL, params=params, timeout=30)
    #爬虫FRED的数据
    response.raise_for_status()
    payload = response.json()

    if "error_code" in payload:
        raise RuntimeError(f"FRED API 错误: {payload['error_code']} - {payload.get('error_message', '')}")

    observations = payload.get("observations", [])
    df = pd.DataFrame(observations)
    if df.empty:
        return df

    df = df.rename(columns={"date": "trade_date", "value": series_id.lower()})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df[series_id.lower()] = pd.to_numeric(df[series_id.lower()].replace(".", pd.NA), errors="coerce")
    return df[["trade_date", series_id.lower()]]


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取 FRED 序列数据")
    parser.add_argument("--series-id", default="VIXCLS", help="FRED 序列代码，默认 VIXCLS")
    parser.add_argument("--api-key", default=os.getenv("FRED_API_KEY", ""), help="FRED API key")
    parser.add_argument("--start-date", default="2000-01-01", help="起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="CSV 输出目录")
    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("请通过 --api-key 或环境变量 FRED_API_KEY 提供 API key")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = fetch_fred_series(
        series_id=args.series_id,
        api_key=args.api_key,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    output_path = output_dir / f"{args.series_id.lower()}.csv"
    df.to_csv(output_path, index=False)

    print("=" * 60)
    print(f"FRED 序列下载完成: {args.series_id}")
    print("=" * 60)
    print(f"输出文件: {output_path}")
    print(f"记录数: {len(df)}")
    if not df.empty:
        print(f"时间范围: {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")
        print("\n最新5条:")
        print(df.tail().to_string(index=False))


if __name__ == "__main__":
    main()

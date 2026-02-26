# test_tushare_history.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_fetcher.tushare_client import TushareClient

client = TushareClient()

# 测试历史数据范围
test_ranges = [
    ("20260101", "20260225", "2026年"),
    ("20250101", "20251231", "2025年"),
    ("20240101", "20241231", "2024年"),
    ("20230101", "20231231", "2023年"),
    ("20220101", "20221231", "2022年"),
    ("20200101", "20201231", "2020年"),
]

print("测试Tushare历史数据范围:\n")

for start, end, desc in test_ranges:
    print(f"{desc} ({start} ~ {end}):")
    try:
        # 用主力连续合约
        df = client.get_futures_daily("NI.SHF", start, end)
        if df is not None and len(df) > 0:
            print(f"  ✓ {len(df)} 条, 首条: {df['trade_date'].iloc[-1]}, 末条: {df['trade_date'].iloc[0]}")
        else:
            print(f"  ✗ 无数据")
    except Exception as e:
        print(f"  ✗ {e}")
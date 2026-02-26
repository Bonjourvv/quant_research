import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_fetcher.ths_client import THSClient

client = THSClient()

print("测试同花顺高频数据:\n")

try:
    data = client.get_high_frequency(
        "NI2603.SHF",
        "2026-02-26 09:15:00",
        "2026-02-26 10:15:00",  # 先测1小时
        period=1
    )
    print(f"返回 {len(data)} 条数据")
    for row in data[:5]:
        print(row)
except Exception as e:
    print(f"错误: {e}")
#!/usr/bin/env python3
"""研究系统统一 CLI 入口。"""

import argparse

from src.pipelines import ResearchConfig, run_mode


def main() -> None:
    parser = argparse.ArgumentParser(description="沪镍展期收益率因子分析")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["realtime", "history", "threshold", "ic", "momentum", "macd", "virtual_ratio", "all"],
        help="运行模式",
    )
    parser.add_argument("--product", default="NI", help="研究品种，默认 NI")
    parser.add_argument("--start-date", default="20150401", help="历史起始日，格式 YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="历史结束日，默认今天")
    parser.add_argument("--min-oi", type=int, default=1000, help="最小持仓量过滤")
    parser.add_argument(
        "--ry-method",
        default="weighted_avg",
        choices=["weighted_avg", "median", "dominant", "curve_fit"],
        help="展期收益率汇总方法",
    )
    parser.add_argument("--no-cache", action="store_true", help="不使用本地缓存")

    args = parser.parse_args()
    config = ResearchConfig(
        product=args.product.upper(),
        start_date=args.start_date,
        end_date=args.end_date,
        min_oi=args.min_oi,
        ry_method=args.ry_method,
        use_cache=not args.no_cache,
    )
    run_mode(args.mode, config)


if __name__ == "__main__":
    main()

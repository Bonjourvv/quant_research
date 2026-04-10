"""
研究流程编排。

把“数据获取/因子计算/结果输出”串起来，CLI 入口只负责解析参数。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from config.settings import (
    DEFAULT_MIN_OI,
    DEFAULT_PRODUCT,
    DEFAULT_RY_METHOD,
    DEFAULT_START_DATE,
    PRODUCT_CONFIG,
    PROCESSED_DATA_DIR,
)
from src.factors.ic_analysis import FactorICAnalyzer
from src.factors.macd import MACDFactor, MACDICAnalyzer, load_dominant_price
from src.factors.momentum import MomentumFactor
from src.factors.roll_yield import RollYieldFactor, RollYieldHistory
from src.factors.threshold import ThresholdCalculator
from src.factors.virtual_real_ratio import (
    VirtualRealRatioFactor,
    load_dominant_contract_features,
)
from src.strategies.ni_vix_panic_reversion import NickelVIXPanicReversionStrategy
from src.strategies.vix_panic_reversion import VIXPanicReversionStrategy
from src.plotting import setup_chinese_font
from src.reporting import export_factor_manual_pdf, export_pdf_report

setup_chinese_font()


@dataclass
class ResearchConfig:
    product: str = DEFAULT_PRODUCT
    start_date: str = DEFAULT_START_DATE
    end_date: Optional[str] = None
    ry_method: str = DEFAULT_RY_METHOD
    min_oi: int = DEFAULT_MIN_OI
    bullish_quantile: float = 0.25
    bearish_quantile: float = 0.75
    use_cache: bool = True
    cache_dir: Path = PROCESSED_DATA_DIR
    output_dir: Path = PROCESSED_DATA_DIR


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def _get_product_name(product: str) -> str:
    return PRODUCT_CONFIG.get(product.upper(), {}).get("name", product.upper())


def _resolve_products(product: str) -> List[str]:
    product = (product or "").upper()
    if not product or product == "ALL":
        return ["NI", "SS"]
    return [product]


def _get_output_base_dir(config: ResearchConfig) -> Path:
    product_dir = config.output_dir / config.product.lower()
    product_dir.mkdir(parents=True, exist_ok=True)
    return product_dir


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _save_latest_summary(output_dir: Path, title: str, lines: List[str]) -> None:
    content = "\n".join([f"# {title}", ""] + lines).strip() + "\n"
    _write_text_file(output_dir / "latest_summary.md", content)


def _format_date(value) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _print_realtime_report(product: str, contracts_df: pd.DataFrame, pairs_df: pd.DataFrame, summary: dict) -> None:
    product_name = _get_product_name(product)

    if not summary:
        _print_header(f"{product_name} 展期收益率分析")
        print("  无可用实时数据")
        print("=" * 80 + "\n")
        return

    _print_header(f"{product_name} 展期收益率分析  |  {summary.get('timestamp', '')}")

    print("\n【活跃合约行情】")
    if contracts_df.empty:
        print("  无数据")
    else:
        print(f"  {'合约':<10} {'价格':>12} {'持仓量':>12} {'剩余天数':>10} {'到期日':>12}")
        print("  " + "-" * 58)
        max_oi = contracts_df["oi"].max()
        for _, row in contracts_df.iterrows():
            marker = " ★" if row["oi"] == max_oi else ""
            print(
                f"  {row['contract']:<10} {row['price']:>12,.0f} {row['oi']:>12,.0f} "
                f"{row['days']:>10} {row['expiry_date']:>12}{marker}"
            )
        print("  " + "-" * 58)
        print("  ★ 主力合约（持仓量最大）")

    print("\n【相邻合约对展期收益率】")
    if pairs_df.empty:
        print("  无数据")
    else:
        print(f"  {'合约对':<20} {'价差':>10} {'天数差':>8} {'年化展期收益率':>14} {'结构':>14}")
        print("  " + "-" * 70)
        for _, row in pairs_df.iterrows():
            ry_str = f"{row['roll_yield_pct']:>+.2f}%" if pd.notna(row["roll_yield_pct"]) else "N/A"
            structure_label = "contango" if row["structure"] == "contango" else "backwardation"
            print(
                f"  {row['pair']:<20} {row['spread']:>+10,.0f} {row['day_diff']:>8} "
                f"{ry_str:>14} {structure_label:>14}"
            )

    print("\n【汇总统计】")
    print(f"  持仓量加权平均:  {summary['weighted_avg']*100:>+8.2f}%")
    print(f"  简单平均:        {summary['simple_avg']*100:>+8.2f}%")
    print(f"  中位数:          {summary['median']*100:>+8.2f}%")
    print(f"  主力-次主力:     {summary['dominant_ry']*100:>+8.2f}%")
    print(f"  期限结构:        {summary['structure']}")

    ry = summary["weighted_avg"]
    if ry < -0.05:
        signal = "bullish (贴水深，利于做多)"
    elif ry > 0.05:
        signal = "bearish (升水深，利于做空)"
    else:
        signal = "neutral"
    print(f"  交易信号:        {signal}")
    print("=" * 80 + "\n")


def run_realtime(config: ResearchConfig) -> None:
    _print_header("[实时] 展期收益率表格")

    factor = RollYieldFactor()

    products = [product.lower() for product in _resolve_products(config.product)]

    for product in products:
        contracts_df, pairs_df, summary = factor.get_realtime_roll_yield_table(product, config.min_oi)
        _print_realtime_report(product, contracts_df, pairs_df, summary)

        if summary and not pairs_df.empty:
            product_config = replace(config, product=product.upper())
            output_dir = _get_output_base_dir(product_config)
            pairs_df.to_csv(output_dir / f"{product}_realtime_pairs.csv", index=False)


def run_history(config: ResearchConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    _print_header("[历史] 展期收益率计算")

    from src.data_fetcher.tushare_client import TushareClient

    contracts_cache = config.cache_dir / f"{config.product.lower()}_contracts_daily.csv"
    ry_cache = config.cache_dir / f"{config.product.lower()}_roll_yield_{config.ry_method}.csv"
    target_end_date = (config.end_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
    ts_client = TushareClient()

    if config.use_cache and contracts_cache.exists():
        print(f"从缓存加载合约数据: {contracts_cache}")
        contracts_data = pd.read_csv(contracts_cache, dtype={"trade_date": str})
        last_cached_date = contracts_data["trade_date"].astype(str).max()

        if last_cached_date < target_end_date:
            latest_slice = contracts_data[contracts_data["trade_date"].astype(str) == last_cached_date].copy()
            probe_contract = latest_slice.sort_values("oi", ascending=False)["ts_code"].iloc[0]
            available_end_date = ts_client.get_latest_available_trade_date(
                ts_code=probe_contract,
                start_date=last_cached_date,
                end_date=target_end_date,
            )

            if available_end_date:
                print(f"历史行情当前最新可用日期: {available_end_date}")
            else:
                print("未探测到比缓存更晚的历史交易日，继续使用现有缓存")

            if available_end_date and available_end_date > last_cached_date:
                print(f"检测到历史缓存较旧，开始增量更新: {last_cached_date} -> {available_end_date}")
                contracts_data = ts_client.update_all_contracts_daily(
                    product=config.product,
                    existing_data=contracts_data,
                    end_date=available_end_date,
                    min_oi=config.min_oi,
                )
                config.cache_dir.mkdir(parents=True, exist_ok=True)
                contracts_data.to_csv(contracts_cache, index=False)
                print(f"已更新合约缓存: {contracts_cache}")
    else:
        print("从Tushare获取合约数据...")
        calc = RollYieldHistory(ts_client)
        contracts_data = calc.load_all_contracts_data(
            product=config.product,
            start_date=config.start_date,
            end_date=target_end_date,
            cache_file=str(contracts_cache) if config.use_cache else None,
        )

        # 强制刷新时也把最新结果写回缓存，避免后续分析继续读旧文件。
        if not config.use_cache:
            config.cache_dir.mkdir(parents=True, exist_ok=True)
            contracts_data.to_csv(contracts_cache, index=False)
            print(f"已更新合约缓存: {contracts_cache}")

    print(f"合约数据: {len(contracts_data)} 条记录")

    latest_contract_date = contracts_data["trade_date"].astype(str).max()
    latest_ry_date = None

    if config.use_cache and ry_cache.exists():
        print(f"从缓存加载展期收益率: {ry_cache}")
        ry_data = pd.read_csv(ry_cache, parse_dates=["trade_date"])
        latest_ry_date = ry_data["trade_date"].dt.strftime("%Y%m%d").max()
    else:
        ry_data = None

    if ry_data is None or latest_ry_date != latest_contract_date:
        print("计算历史展期收益率...")
        calc = RollYieldHistory()
        calc._data_cache = contracts_data

        ry_data = calc.calc_history_roll_yield(
            method=config.ry_method,
            min_oi=config.min_oi,
        )

        config.cache_dir.mkdir(parents=True, exist_ok=True)
        ry_data.to_csv(ry_cache, index=False)
        print(f"已保存到: {ry_cache}")

    print("\n【历史展期收益率统计】")
    print(f"  时间范围: {ry_data['trade_date'].min()} ~ {ry_data['trade_date'].max()}")
    print(f"  样本数量: {len(ry_data)}")
    print(f"  均值: {ry_data['roll_yield'].mean()*100:.2f}%")
    print(f"  标准差: {ry_data['roll_yield'].std()*100:.2f}%")
    print(f"  最小值: {ry_data['roll_yield'].min()*100:.2f}%")
    print(f"  最大值: {ry_data['roll_yield'].max()*100:.2f}%")

    latest = ry_data.sort_values("trade_date").iloc[-1]
    output_dir = _get_output_base_dir(config)
    _save_latest_summary(
        output_dir,
        f"{_get_product_name(config.product)} 展期收益率摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 最新展期收益率: {latest['roll_yield']*100:+.2f}%",
            f"- 样本数量: {len(ry_data)}",
            f"- 历史均值: {ry_data['roll_yield'].mean()*100:+.2f}%",
            f"- 历史标准差: {ry_data['roll_yield'].std()*100:.2f}%",
        ],
    )

    return ry_data, contracts_data


def run_threshold(config: ResearchConfig, ry_data: pd.DataFrame) -> dict:
    _print_header("[阈值] 分位数计算")

    calc = ThresholdCalculator(ry_data)
    thresholds = calc.calc_fixed_threshold(
        bullish_quantile=config.bullish_quantile,
        bearish_quantile=config.bearish_quantile,
    )
    calc.print_threshold_report(thresholds)
    return thresholds


def run_ic_analysis(config: ResearchConfig, ry_data: pd.DataFrame, contracts_data: pd.DataFrame) -> FactorICAnalyzer:
    _print_header("[IC] 因子相关性分析")

    contracts_data = contracts_data.copy()
    contracts_data["trade_date"] = contracts_data["trade_date"].astype(str)
    idx = contracts_data.groupby("trade_date")["oi"].idxmax()
    price_data = contracts_data.loc[idx, ["trade_date", "close"]].copy()
    price_data["trade_date"] = pd.to_datetime(price_data["trade_date"])
    price_data = price_data.sort_values("trade_date")

    print(f"价格数据: {len(price_data)} 条")

    analyzer = FactorICAnalyzer(ry_data, price_data)
    analyzer.print_analysis_report()

    analyzer.export_results(str(_get_output_base_dir(config)))
    return analyzer


def run_momentum_analysis(config: ResearchConfig, contracts_data: pd.DataFrame) -> FactorICAnalyzer:
    _print_header("[动量] 价格动量因子分析")

    price_data = load_dominant_price(contracts_data)
    momentum = MomentumFactor()
    signal_data, _ = momentum.print_analysis_report(price_data)
    momentum_dir = _get_output_base_dir(config) / "momentum"
    momentum_dir.mkdir(parents=True, exist_ok=True)

    factor_data = signal_data[["trade_date", "momentum_return"]].rename(columns={"momentum_return": "momentum_factor"})
    analyzer = FactorICAnalyzer(
        factor_data=factor_data,
        price_data=price_data,
        factor_col="momentum_factor",
        factor_name="momentum",
        lower_factor_is_bullish=False,
    )
    analyzer.print_analysis_report()
    analyzer.export_results(str(momentum_dir))
    signal_data.to_csv(momentum_dir / "momentum_signals.csv", index=False)
    _save_latest_summary(
        momentum_dir,
        f"{_get_product_name(config.product)} 动量因子摘要",
        [
            f"- 日期: {_format_date(signal_data.dropna(subset=['momentum_return']).iloc[-1]['trade_date'])}",
            f"- 最新收盘价: {signal_data.dropna(subset=['momentum_return']).iloc[-1]['close']:.2f}",
            f"- 20日动量: {signal_data.dropna(subset=['momentum_return']).iloc[-1]['momentum_return']*100:+.2f}%",
            f"- 趋势强度: {signal_data.dropna(subset=['momentum_return']).iloc[-1]['trend_strength']*100:+.2f}%",
            f"- 趋势标签: {signal_data.dropna(subset=['momentum_return']).iloc[-1]['trend_label']}",
            f"- 交易信号: {int(signal_data.dropna(subset=['momentum_return']).iloc[-1]['signal']):+d}",
        ],
    )
    return analyzer


def run_macd_analysis(config: ResearchConfig, contracts_data: pd.DataFrame) -> pd.DataFrame:
    _print_header("[MACD] 趋势与信号分析")

    price_data = load_dominant_price(contracts_data)
    macd = MACDFactor()
    signal_data, _ = macd.print_analysis_report(price_data)
    latest = macd.summarize_latest_trend(signal_data)
    macd_dir = _get_output_base_dir(config) / "macd"
    macd_dir.mkdir(parents=True, exist_ok=True)
    macd.export_results(signal_data, str(macd_dir))
    _save_latest_summary(
        macd_dir,
        f"{_get_product_name(config.product)} MACD 因子摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 当前趋势: {latest['trend']}",
            f"- DIF / DEA: {latest['dif']:.2f} / {latest['dea']:.2f}",
            f"- MACD柱: {latest['macd_hist']:.2f}",
            f"- 当前信号: {latest['signal']:+d}",
            f"- 当前持仓: {latest['position']:+d}",
        ],
    )
    return signal_data


def run_virtual_ratio_analysis(config: ResearchConfig, contracts_data: pd.DataFrame) -> FactorICAnalyzer:
    _print_header("[虚实盘比] 成交与持仓结构分析")

    dominant_data = load_dominant_contract_features(contracts_data)
    factor = VirtualRealRatioFactor()
    factor_data, latest = factor.print_analysis_report(dominant_data)

    vr_dir = _get_output_base_dir(config) / "virtual_ratio"
    vr_dir.mkdir(parents=True, exist_ok=True)
    factor_data.to_csv(vr_dir / "virtual_ratio_signals.csv", index=False)

    analyzer = FactorICAnalyzer(
        factor_data=factor_data[["trade_date", "virtual_real_ratio"]],
        price_data=dominant_data[["trade_date", "close"]],
        factor_col="virtual_real_ratio",
        factor_name="virtual_real_ratio",
        lower_factor_is_bullish=True,
    )
    analyzer.print_analysis_report()
    analyzer.export_results(str(vr_dir))

    try:
        realtime_factor = RollYieldFactor()
        contracts = realtime_factor.get_contracts_by_oi(config.product.lower(), config.min_oi)
        if contracts:
            snapshot = factor.fetch_realtime_snapshot(contracts[0]["code"])
            interpreted = factor.interpret_snapshot(snapshot)
            print("\n【实时快照】")
            print(f"  时间: {interpreted['timestamp']}")
            print(f"  合约: {interpreted['contract_code']}")
            print(f"  最新价: {interpreted['latest']:.2f}")
            print(f"  成交量: {interpreted['volume']:.0f}")
            print(f"  持仓量: {interpreted['open_interest']:.0f}")
            print(f"  虚实盘比: {interpreted['virtual_real_ratio']:.3f}")
            print(f"  解读: {interpreted['status']}")
            pd.DataFrame([interpreted]).to_csv(vr_dir / "virtual_ratio_realtime_snapshot.csv", index=False)
    except Exception as exc:
        print(f"\n  跳过实时虚实盘比快照: {exc}")

    _save_latest_summary(
        vr_dir,
        f"{_get_product_name(config.product)} 虚实盘比摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 主力合约: {latest['dominant_code']}",
            f"- 收盘价: {latest['close']:.2f}",
            f"- 虚实盘比: {latest['virtual_real_ratio']:.3f}",
            f"- 持仓变化: {latest['oi_change']:+.0f}",
            f"- 成交变化: {latest['vol_change']:+.0f}",
            f"- 交易信号: {latest['signal']}",
            f"- 信号解读: {latest['signal_text']}",
        ],
    )

    return analyzer


def _build_product_snapshot(config: ResearchConfig) -> Dict[str, str]:
    product_name = _get_product_name(config.product)
    ry_data, contracts_data = run_history(config)

    latest_ry = ry_data.sort_values("trade_date").iloc[-1]
    price_data = load_dominant_price(contracts_data)

    momentum = MomentumFactor()
    momentum_signal = momentum.generate_signals(momentum.calc_momentum(price_data))
    momentum_latest = momentum.summarize_latest(momentum_signal)

    macd = MACDFactor()
    macd_signal = macd.generate_signals(macd.calc_macd(price_data))
    macd_latest = macd.summarize_latest_trend(macd_signal)

    vr_factor = VirtualRealRatioFactor()
    dominant_data = load_dominant_contract_features(contracts_data)
    vr_data = vr_factor.calc_factor_values(dominant_data)
    vr_latest = vr_data.dropna(subset=["virtual_real_ratio"]).iloc[-1]

    snapshot = {
        "品种": product_name,
        "代码": config.product.upper(),
        "历史最新日期": _format_date(latest_ry["trade_date"]),
        "展期收益率": f"{latest_ry['roll_yield']*100:+.2f}%",
        "动量趋势": str(momentum_latest["trend_label"]),
        "动量信号": f"{int(momentum_latest['signal']):+d}",
        "MACD趋势": str(macd_latest["trend"]),
        "MACD持仓": f"{int(macd_latest['position']):+d}",
        "虚实盘比": f"{vr_latest['virtual_real_ratio']:.3f}",
        "虚实盘信号": str(vr_latest["signal"]),
        "虚实盘解读": str(vr_latest["signal_text"]),
    }

    try:
        realtime_factor = RollYieldFactor()
        _, _, realtime_summary = realtime_factor.get_realtime_roll_yield_table(config.product.lower(), config.min_oi)
        if realtime_summary:
            snapshot["实时展期信号"] = str(realtime_summary.get("structure", ""))
            snapshot["实时展期均值"] = f"{realtime_summary.get('weighted_avg', 0)*100:+.2f}%"
    except Exception:
        snapshot["实时展期信号"] = ""
        snapshot["实时展期均值"] = ""

    return snapshot


def run_summary(config: ResearchConfig) -> None:
    _print_header("双品种因子汇总页")
    summary_dir = config.output_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    snapshots = []
    products = ["NI", "SS"] if config.product.upper() == DEFAULT_PRODUCT else _resolve_products(config.product)
    for product in products:
        product_config = replace(config, product=product)
        snapshots.append(_build_product_snapshot(product_config))

    summary_df = pd.DataFrame(snapshots)
    summary_csv = summary_dir / "latest_factor_summary.csv"
    summary_df.to_csv(summary_csv, index=False)

    markdown_lines = [
        f"# 双品种因子汇总页",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for snapshot in snapshots:
        print(f"\n【{snapshot['品种']}】")
        print(f"  历史最新日期: {snapshot['历史最新日期']}")
        print(f"  展期收益率: {snapshot['展期收益率']}")
        if snapshot.get("实时展期均值"):
            print(f"  实时展期均值: {snapshot['实时展期均值']}")
        print(f"  动量趋势 / 信号: {snapshot['动量趋势']} / {snapshot['动量信号']}")
        print(f"  MACD趋势 / 持仓: {snapshot['MACD趋势']} / {snapshot['MACD持仓']}")
        print(f"  虚实盘比 / 信号: {snapshot['虚实盘比']} / {snapshot['虚实盘信号']}")
        print(f"  虚实盘解读: {snapshot['虚实盘解读']}")

        markdown_lines.extend(
            [
                f"## {snapshot['品种']}",
                "",
                f"- 历史最新日期: {snapshot['历史最新日期']}",
                f"- 展期收益率: {snapshot['展期收益率']}",
                f"- 实时展期均值: {snapshot.get('实时展期均值', '')}",
                f"- 动量趋势 / 信号: {snapshot['动量趋势']} / {snapshot['动量信号']}",
                f"- MACD趋势 / 持仓: {snapshot['MACD趋势']} / {snapshot['MACD持仓']}",
                f"- 虚实盘比 / 信号: {snapshot['虚实盘比']} / {snapshot['虚实盘信号']}",
                f"- 虚实盘解读: {snapshot['虚实盘解读']}",
                "",
            ]
        )

    summary_md = summary_dir / "latest_factor_summary.md"
    _write_text_file(summary_md, "\n".join(markdown_lines).rstrip() + "\n")
    print(f"\n汇总文件已导出到: {summary_md}")
    print(f"汇总表已导出到: {summary_csv}")


def _calc_quant_factor_metrics(
    factor_name: str,
    analyzer: FactorICAnalyzer,
    product_name: str,
    product_code: str,
) -> Dict[str, object]:
    ic_summary = analyzer.calc_ic_summary()
    backtest = analyzer.run_quantile_backtest(period=3)

    ic_3d = ic_summary.loc[ic_summary["period"] == "3D"].iloc[0]
    ic_5d = ic_summary.loc[ic_summary["period"] == "5D"].iloc[0]

    strategy_total_return = backtest["strategy_nav"].iloc[-1] - 1 if not backtest.empty else 0.0
    benchmark_total_return = backtest["benchmark_nav"].iloc[-1] - 1 if not backtest.empty else 0.0

    return {
        "factor": factor_name,
        "product": product_code,
        "product_name": product_name,
        "ic_3d": ic_3d["ic"],
        "ic_5d": ic_5d["ic"],
        "abs_ic_5d": abs(ic_5d["ic"]),
        "pvalue_5d": ic_5d["pvalue"],
        "strategy_total_return": strategy_total_return,
        "benchmark_total_return": benchmark_total_return,
        "excess_return": strategy_total_return - benchmark_total_return,
        "metric_label": "3日持有回测收益",
    }


def _calc_macd_daily_nav(signal_data: pd.DataFrame) -> pd.DataFrame:
    df = signal_data.copy().sort_values("trade_date").reset_index(drop=True)
    df["daily_ret"] = df["close"].pct_change().fillna(0)
    df["strategy_ret"] = df["position"].shift(1).fillna(0) * df["daily_ret"]
    df["strategy_nav"] = (1 + df["strategy_ret"]).cumprod()
    df["benchmark_nav"] = (1 + df["daily_ret"]).cumprod()
    return df


def _calc_macd_metrics(
    signal_data: pd.DataFrame,
    product_name: str,
    product_code: str,
) -> Dict[str, object]:
    ic_analyzer = MACDICAnalyzer(signal_data)
    ic_summary = ic_analyzer.calc_ic()
    macd = MACDFactor()
    signal_stats = macd.analyze_signals(signal_data, [5])[5]
    nav = _calc_macd_daily_nav(signal_data)

    ic_3d = ic_summary.loc[ic_summary["period"] == "3D"].iloc[0]
    ic_5d = ic_summary.loc[ic_summary["period"] == "5D"].iloc[0]

    strategy_total_return = nav["strategy_nav"].iloc[-1] - 1 if not nav.empty else 0.0
    benchmark_total_return = nav["benchmark_nav"].iloc[-1] - 1 if not nav.empty else 0.0

    return {
        "factor": "macd",
        "product": product_code,
        "product_name": product_name,
        "ic_3d": ic_3d["ic"],
        "ic_5d": ic_5d["ic"],
        "abs_ic_5d": abs(ic_5d["ic"]),
        "pvalue_5d": ic_5d["pvalue"],
        "strategy_total_return": strategy_total_return,
        "benchmark_total_return": benchmark_total_return,
        "excess_return": strategy_total_return - benchmark_total_return,
        "metric_label": "日频信号策略收益",
        "signal_long_short_diff_5d": signal_stats["long_short_diff"],
        "signal_win_rate_5d": (signal_stats["golden_cross_win_rate"] + signal_stats["death_cross_win_rate"]) / 2,
    }


def _plot_product_comparison(summary_df: pd.DataFrame, output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    factor_labels = {
        "roll_yield": "展期收益率",
        "momentum": "价格动量",
        "virtual_real_ratio": "虚实盘比",
        "macd": "MACD",
    }
    product_map = {"NI": "沪镍", "SS": "不锈钢"}
    colors = {"NI": "#1f2937", "SS": "#9c6644"}

    abs_ic_path = output_dir / "factor_abs_ic5d_comparison.png"
    excess_path = output_dir / "factor_excess_return_comparison.png"

    factors = ["roll_yield", "momentum", "virtual_real_ratio", "macd"]
    x = range(len(factors))
    width = 0.36

    fig, ax = plt.subplots(figsize=(11, 5))
    for idx, product in enumerate(["NI", "SS"]):
        subset = summary_df[summary_df["product"] == product].set_index("factor")
        values = [subset.loc[factor, "abs_ic_5d"] * 100 for factor in factors]
        ax.bar([i + (idx - 0.5) * width for i in x], values, width=width, label=product_map[product], color=colors[product])
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("|5日IC| (%)")
    ax.set_title("不同品种下各因子准确率对比（|5日IC|）")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(abs_ic_path, dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    for idx, product in enumerate(["NI", "SS"]):
        subset = summary_df[summary_df["product"] == product].set_index("factor")
        values = [subset.loc[factor, "excess_return"] * 100 for factor in factors]
        ax.bar([i + (idx - 0.5) * width for i in x], values, width=width, label=product_map[product], color=colors[product])
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("超额收益 (%)")
    ax.set_title("不同品种下各因子策略超额收益对比")
    ax.axhline(0, color="black", linewidth=1)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(excess_path, dpi=160)
    plt.close(fig)

    return {"abs_ic_chart": abs_ic_path, "excess_chart": excess_path}


def run_compare(config: ResearchConfig) -> None:
    _print_header("品种影响对比回测")

    products = ["NI", "SS"]
    rows: List[Dict[str, object]] = []

    for product in products:
        product_config = replace(config, product=product)
        product_name = _get_product_name(product)
        ry_data, contracts_data = run_history(product_config)
        price_data = load_dominant_price(contracts_data)

        roll_analyzer = FactorICAnalyzer(ry_data, price_data)
        rows.append(_calc_quant_factor_metrics("roll_yield", roll_analyzer, product_name, product))

        momentum = MomentumFactor()
        momentum_signal = momentum.generate_signals(momentum.calc_momentum(price_data))
        momentum_factor = momentum_signal[["trade_date", "momentum_return"]].rename(columns={"momentum_return": "momentum_factor"})
        momentum_analyzer = FactorICAnalyzer(
            factor_data=momentum_factor,
            price_data=price_data,
            factor_col="momentum_factor",
            factor_name="momentum",
            lower_factor_is_bullish=False,
        )
        rows.append(_calc_quant_factor_metrics("momentum", momentum_analyzer, product_name, product))

        vr_factor = VirtualRealRatioFactor()
        dominant_data = load_dominant_contract_features(contracts_data)
        vr_data = vr_factor.calc_factor_values(dominant_data)
        vr_analyzer = FactorICAnalyzer(
            factor_data=vr_data[["trade_date", "virtual_real_ratio"]],
            price_data=dominant_data[["trade_date", "close"]],
            factor_col="virtual_real_ratio",
            factor_name="virtual_real_ratio",
            lower_factor_is_bullish=True,
        )
        rows.append(_calc_quant_factor_metrics("virtual_real_ratio", vr_analyzer, product_name, product))

        macd = MACDFactor()
        macd_signal = macd.generate_signals(macd.calc_macd(price_data))
        rows.append(_calc_macd_metrics(macd_signal, product_name, product))

    summary_df = pd.DataFrame(rows)
    comparison_dir = config.output_dir / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    summary_path = comparison_dir / "factor_product_comparison.csv"
    summary_df.to_csv(summary_path, index=False)

    charts = _plot_product_comparison(summary_df, comparison_dir)

    print("\n【核心对比】")
    print(f"  {'因子':<12} {'品种':<8} {'5日IC':>10} {'|5日IC|':>10} {'策略收益':>12} {'超额收益':>12}")
    print("  " + "-" * 72)
    for _, row in summary_df.iterrows():
        print(
            f"  {row['factor']:<12} {row['product_name']:<8} "
            f"{row['ic_5d']:>+9.4f} {row['abs_ic_5d']*100:>9.2f}% "
            f"{row['strategy_total_return']*100:>+11.2f}% {row['excess_return']*100:>+11.2f}%"
        )

    best_rows = summary_df.loc[summary_df.groupby("factor")["abs_ic_5d"].idxmax()].copy()
    best_rows = best_rows.sort_values("factor")

    markdown_lines = [
        "# 品种影响对比回测",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 结论摘要",
        "",
    ]
    for _, row in best_rows.iterrows():
        markdown_lines.append(
            f"- {row['factor']}：{row['product_name']} 的 |5日IC| 更高，为 {row['abs_ic_5d']*100:.2f}%，"
            f"策略超额收益为 {row['excess_return']*100:+.2f}%"
        )

    markdown_lines.extend(
        [
            "",
            "## 结果文件",
            "",
            f"- 汇总表: {summary_path}",
            f"- 准确率图: {charts['abs_ic_chart']}",
            f"- 超额收益图: {charts['excess_chart']}",
            "",
        ]
    )
    report_path = comparison_dir / "factor_product_comparison.md"
    _write_text_file(report_path, "\n".join(markdown_lines))

    print("\n【结论摘要】")
    for _, row in best_rows.iterrows():
        print(
            f"  {row['factor']}: {row['product_name']} 的 |5日IC| 更高 "
            f"({row['abs_ic_5d']*100:.2f}%)，超额收益 {row['excess_return']*100:+.2f}%"
        )

    print(f"\n对比汇总已导出到: {summary_path}")
    print(f"对比报告已导出到: {report_path}")
    print(f"图表已导出到: {charts}")


def run_vix_panic_reversion(config: ResearchConfig) -> pd.Series:
    _print_header("[VIX] 恐慌反转回测")

    from src.data_fetcher.fred_client import FredClient

    fred = FredClient()
    price_data = fred.get_series("SP500", start_date=config.start_date, end_date=config.end_date)
    vix_data = fred.get_series("VIXCLS", start_date=config.start_date, end_date=config.end_date)

    strategy = VIXPanicReversionStrategy()
    merged = strategy.prepare_data(price_data, vix_data)
    signal_data = strategy.signal_generation(merged)
    portfolio = strategy.backtest(signal_data)
    summary = strategy.print_report(portfolio)

    output_dir = config.output_dir / "vix_panic_reversion"
    paths = strategy.export_results(portfolio, output_dir)
    print(f"结果已导出到: {output_dir}/")
    print(f"导出文件: {paths}")
    return summary


def run_nickel_vix_panic_reversion(config: ResearchConfig) -> pd.Series:
    _print_header("[VIX+沪镍] 恐慌反转回测")

    from src.data_fetcher.fred_client import FredClient

    nickel_config = replace(config, product="NI")
    _, contracts_data = run_history(nickel_config)
    price_data = load_dominant_price(contracts_data)[["trade_date", "close"]].copy()

    fred = FredClient()
    vix_data = fred.get_series("VIXCLS", start_date=config.start_date, end_date=config.end_date)

    strategy = NickelVIXPanicReversionStrategy()
    merged = strategy.prepare_data(price_data, vix_data)
    signal_data = strategy.signal_generation(merged)
    portfolio = strategy.backtest(signal_data)
    summary = strategy.print_report(portfolio)

    output_dir = config.output_dir / "ni_vix_panic_reversion"
    paths = strategy.export_results(portfolio, output_dir)
    print(f"结果已导出到: {output_dir}/")
    print(f"导出文件: {paths}")
    return summary


def run_all(config: ResearchConfig) -> None:
    _print_header(f"{_get_product_name(config.product)} 因子完整分析")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    _print_header("[1/6] 实时展期收益率表格")
    try:
        run_realtime(config)
    except Exception as exc:
        print(f"  跳过实时数据（需要同花顺API）: {exc}")

    _print_header("[2/6] 历史展期收益率计算")
    ry_data, contracts_data = run_history(config)

    _print_header("[3/6] 分位数阈值计算")
    run_threshold(config, ry_data)

    _print_header("[4/6] 因子IC分析")
    run_ic_analysis(config, ry_data, contracts_data)

    _print_header("[5/7] 价格动量因子")
    run_momentum_analysis(config, contracts_data)

    _print_header("[6/7] MACD 趋势分析")
    run_macd_analysis(config, contracts_data)

    _print_header("[7/7] 虚实盘比因子")
    run_virtual_ratio_analysis(config, contracts_data)

    _print_header("分析完成！")
    product_output_dir = _get_output_base_dir(config)
    print(f"\n  输出文件位置: {product_output_dir}/")
    print(f"  - {config.product.lower()}_roll_yield_weighted_avg.csv  历史展期收益率")
    print("  - ic_summary.csv                  IC统计汇总")
    print("  - group_returns.csv               分组收益分析")
    print("  - factor_returns.csv              因子与收益率数据")
    print("  - backtest_nav.csv                回测净值序列")
    print("  - *.png                           回测图 / 因子诊断图")
    print("  - virtual_ratio/                  虚实盘比因子结果")
    print("=" * 80 + "\n")


def run_all_products(config: ResearchConfig) -> None:
    _print_header("双品种完整分析")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    run_summary(replace(config, product="ALL"))

    for product in ["NI", "SS"]:
        product_config = replace(config, product=product)
        _print_header(f"{_get_product_name(product)} 完整分析")
        run_all(product_config)

    _print_header("双品种输出完成")
    print(f"  汇总页: {config.output_dir / 'summary'}/")
    print(f"  沪镍结果: {config.output_dir / 'ni'}/")
    print(f"  不锈钢结果: {config.output_dir / 'ss'}/")
    print("=" * 80 + "\n")


def run_pdf_report(config: ResearchConfig) -> Path:
    _print_header("[PDF] 研究报告导出")

    product = config.product.upper()
    if product == "ALL":
        summary_path = config.output_dir / "summary" / "latest_factor_summary.md"
        if not summary_path.exists():
            print("未找到双品种摘要，先生成 summary...")
            run_summary(replace(config, product="ALL"))
    else:
        product_dir = _get_output_base_dir(config)
        if not (product_dir / "latest_summary.md").exists():
            print("未找到品种摘要，先生成完整分析结果...")
            run_all(config)

    pdf_path = export_pdf_report(product=product, output_dir=config.output_dir)
    print(f"PDF 已导出到: {pdf_path}")
    return pdf_path


def run_factor_manual_pdf(config: ResearchConfig) -> Path:
    _print_header("[PDF] 因子手册导出")
    pdf_path = export_factor_manual_pdf(output_dir=config.output_dir)
    print(f"因子手册已导出到: {pdf_path}")
    return pdf_path


def run_mode(mode: str, config: Optional[ResearchConfig] = None) -> None:
    config = config or ResearchConfig()

    if mode == "realtime":
        run_realtime(config)
    elif mode == "history":
        run_history(config)
    elif mode == "threshold":
        ry_data, _ = run_history(config)
        run_threshold(config, ry_data)
    elif mode == "ic":
        ry_data, contracts_data = run_history(config)
        run_ic_analysis(config, ry_data, contracts_data)
    elif mode == "momentum":
        _, contracts_data = run_history(config)
        run_momentum_analysis(config, contracts_data)
    elif mode == "macd":
        _, contracts_data = run_history(config)
        run_macd_analysis(config, contracts_data)
    elif mode == "virtual_ratio":
        _, contracts_data = run_history(config)
        run_virtual_ratio_analysis(config, contracts_data)
    elif mode == "summary":
        run_summary(config)
    elif mode == "compare":
        run_compare(config)
    elif mode == "vix_panic":
        run_vix_panic_reversion(config)
    elif mode == "ni_vix_panic":
        run_nickel_vix_panic_reversion(config)
    elif mode == "pdf":
        run_pdf_report(config)
    elif mode == "manual_pdf":
        run_factor_manual_pdf(config)
    else:
        if mode == "all":
            run_all_products(replace(config, product="ALL"))
        elif config.product.upper() == "ALL":
            run_all_products(config)
        else:
            run_all(config)

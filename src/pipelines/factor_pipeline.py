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
from src.factors.intraday_skew import IntradaySkewFactor, load_dominant_contract_by_date
from src.factors.macd import MACDFactor, MACDICAnalyzer, load_dominant_price
from src.factors.momentum import MomentumFactor
from src.factors.position_price_flow import (
    PositionPriceFlowFactor,
    load_dominant_contract_data,
)
from src.strategies.roll_virtual_combo import RollVirtualComboFactor
from src.factors.roll_yield import RollYieldFactor, RollYieldHistory
from src.factors.threshold import ThresholdCalculator
from src.factors.virtual_real_ratio import (
    VirtualRealRatioFactor,
    load_dominant_contract_features,
)
from src.strategies.ni_vix_panic_reversion import NickelVIXPanicReversionStrategy
from src.strategies.commodity_vix_panic_reversion import CommodityVIXPanicReversionStrategy
from src.strategies.vix_panic_reversion import VIXPanicReversionStrategy
from src.plotting import setup_chinese_font
from src.reporting import (
    export_comprehensive_report,
    export_factor_manual_latex,
    export_factor_manual_pdf,
    export_pdf_report,
    export_signal_table_image,
)

setup_chinese_font()


@dataclass
class ResearchConfig:
    product: str = DEFAULT_PRODUCT
    start_date: str = DEFAULT_START_DATE
    end_date: Optional[str] = None
    ry_method: str = DEFAULT_RY_METHOD
    min_oi: int = DEFAULT_MIN_OI
    bullish_quantile: float = 0.10
    bearish_quantile: float = 0.90
    use_cache: bool = True
    denoise: bool = False
    smooth_window: int = 3
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
        return ["NI", "SS", "CU"]
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


def _augment_contracts_with_ths_latest(config: ResearchConfig, contracts_data: pd.DataFrame) -> pd.DataFrame:
    """
    用同花顺实时主力快照给历史主库补一条“当日临时记录”。

    这条补丁只服务于需要最新日内状态的因子展示，不回写历史缓存，
    也不替代 Tushare 的正式历史日线。
    """
    try:
        today = pd.Timestamp.now().normalize()
        latest_cached = pd.to_datetime(contracts_data["trade_date"].astype(str)).max().normalize()
        if latest_cached >= today:
            return contracts_data

        realtime_factor = RollYieldFactor()
        contracts = realtime_factor.get_contracts_by_oi(config.product.lower(), config.min_oi)
        if not contracts:
            return contracts_data

        dominant_contract = contracts[0]

        from src.data_fetcher.ths_client import THSClient

        quote = THSClient().get_realtime_quote(dominant_contract["code"])
        if not quote:
            return contracts_data

        patched = contracts_data.copy()
        row = {col: None for col in patched.columns}
        row.update(
            {
                "ts_code": dominant_contract["code"],
                "trade_date": today.strftime("%Y%m%d"),
                "close": float(quote.get("latest", 0) or 0),
                "oi": float(quote.get("openInterest", 0) or 0),
                "vol": float(quote.get("volume", 0) or 0),
            }
        )
        if "open" in patched.columns:
            row["open"] = float(quote.get("open", 0) or row["close"])
        if "high" in patched.columns:
            row["high"] = float(quote.get("high", 0) or row["close"])
        if "low" in patched.columns:
            row["low"] = float(quote.get("low", 0) or row["close"])

        patched = pd.concat([patched, pd.DataFrame([row])], ignore_index=True)
        patched["trade_date"] = patched["trade_date"].astype(str)
        patched = patched.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        return patched
    except Exception as exc:
        print(f"  跳过同花顺最新价补丁: {exc}")
        return contracts_data


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
    ts_client = None

    if config.use_cache and contracts_cache.exists():
        print(f"从缓存加载合约数据: {contracts_cache}")
        contracts_data = pd.read_csv(contracts_cache, dtype={"trade_date": str})
        last_cached_date = contracts_data["trade_date"].astype(str).max()

        if last_cached_date < target_end_date:
            try:
                ts_client = TushareClient()
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
            except ValueError as exc:
                print(f"{exc}")
                print("检测到 Tushare 不可用，跳过在线更新，继续使用本地历史缓存")
    else:
        print("从Tushare获取合约数据...")
        ts_client = TushareClient()
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

    contracts_data = _augment_contracts_with_ths_latest(config, contracts_data)
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

    contracts_data = _augment_contracts_with_ths_latest(config, contracts_data)
    price_data = load_dominant_price(contracts_data)
    macd = MACDFactor(denoise=config.denoise, smooth_window=config.smooth_window)
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


def run_intraday_skew_analysis(config: ResearchConfig, contracts_data: pd.DataFrame) -> FactorICAnalyzer:
    _print_header("[偏度因子] 5分钟收益率偏度")

    contracts_data = _augment_contracts_with_ths_latest(config, contracts_data)
    dominant_data = load_dominant_contract_by_date(contracts_data)
    output_dir = _get_output_base_dir(config) / "intraday_skew"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_file = output_dir / "intraday_skew_signals.csv"

    factor = IntradaySkewFactor()
    factor_data = factor.build_factor_series(dominant_data, cache_file=cache_file)
    factor_data, latest = factor.print_analysis_report(factor_data)
    factor_data.to_csv(cache_file, index=False)

    analyzer = FactorICAnalyzer(
        factor_data=factor_data[["trade_date", "skew_factor"]],
        price_data=factor_data[["trade_date", "close"]],
        factor_col="skew_factor",
        factor_name="intraday_skew",
        lower_factor_is_bullish=True,
    )
    analyzer.print_analysis_report()
    analyzer.export_results(str(output_dir))

    _save_latest_summary(
        output_dir,
        f"{_get_product_name(config.product)} 5分钟偏度因子摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 主力合约: {latest['dominant_code']}",
            f"- 收盘价: {latest['close']:.2f}",
            f"- 偏度因子: {latest['skew_factor']:+.4f}",
            f"- 上行偏度: {latest['upside_skew']:+.4f}",
            f"- 下行偏度: {latest['downside_skew']:+.4f}",
            f"- 交易信号: {latest['signal']}",
            f"- 信号解读: {latest['signal_text']}",
        ],
    )

    return analyzer


def run_roll_virtual_combo_analysis(
    config: ResearchConfig,
    ry_data: pd.DataFrame,
    contracts_data: pd.DataFrame,
) -> FactorICAnalyzer:
    _print_header("[组合因子] 展期收益率 + 虚实盘比")

    dominant_data = load_dominant_contract_features(contracts_data)
    vr_factor = VirtualRealRatioFactor()
    vr_data = vr_factor.calc_factor_values(dominant_data)

    combo_factor = RollVirtualComboFactor()
    combo_data = combo_factor.calc_factor_values(ry_data, vr_data)
    combo_data, latest = combo_factor.print_analysis_report(combo_data)

    output_dir = _get_output_base_dir(config) / "roll_virtual_combo"
    output_dir.mkdir(parents=True, exist_ok=True)
    combo_data.to_csv(output_dir / "roll_virtual_combo_signals.csv", index=False)

    analyzer = FactorICAnalyzer(
        factor_data=combo_data[["trade_date", "combo_score"]],
        price_data=combo_data[["trade_date", "close"]],
        factor_col="combo_score",
        factor_name="roll_virtual_combo",
        lower_factor_is_bullish=False,
    )
    analyzer.print_analysis_report()
    analyzer.export_results(str(output_dir))

    _save_latest_summary(
        output_dir,
        f"{_get_product_name(config.product)} 展期+虚实盘组合摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 主力合约: {latest['dominant_code']}",
            f"- 收盘价: {latest['close']:.2f}",
            f"- 展期收益率: {latest['roll_yield']*100:+.2f}%",
            f"- 虚实盘比: {latest['virtual_real_ratio']:.3f}",
            f"- 组合得分: {latest['combo_score']:+.2f}",
            f"- 交易信号: {latest['signal']}",
            f"- 信号解读: {latest['signal_text']}",
        ],
    )

    return analyzer


def run_position_flow_analysis(config: ResearchConfig, contracts_data: pd.DataFrame) -> FactorICAnalyzer:
    _print_header("[持仓联动] 持仓-价格联动分析")

    dominant_data = load_dominant_contract_data(contracts_data)
    factor = PositionPriceFlowFactor()
    factor_data, latest = factor.print_analysis_report(dominant_data)

    output_dir = _get_output_base_dir(config) / "position_flow"
    output_dir.mkdir(parents=True, exist_ok=True)
    factor_data.to_csv(output_dir / "position_flow_signals.csv", index=False)

    analyzer = FactorICAnalyzer(
        factor_data=factor_data[["trade_date", "position_flow_factor"]],
        price_data=dominant_data[["trade_date", "close"]],
        factor_col="position_flow_factor",
        factor_name="position_price_flow",
        lower_factor_is_bullish=False,
    )
    analyzer.print_analysis_report()
    analyzer.export_results(str(output_dir))

    try:
        realtime_factor = RollYieldFactor()
        contracts = realtime_factor.get_contracts_by_oi(config.product.lower(), config.min_oi)
        if contracts:
            snapshot = factor.fetch_realtime_snapshot(contracts[0]["code"])
            reference = {
                "oi": latest.get("oi", 0),
                "vol": latest.get("vol", 0),
            }
            interpreted = factor.interpret_snapshot(snapshot, reference)
            print("\n【实时快照】")
            print(f"  时间: {interpreted['timestamp']}")
            print(f"  合约: {interpreted['contract_code']}")
            print(f"  最新价: {interpreted['latest']:.2f}")
            print(f"  日内涨跌: {interpreted['price_change']*100:+.2f}%")
            print(f"  持仓量: {interpreted['open_interest']:.0f}")
            print(f"  相对上日持仓变化: {interpreted['oi_change']:+.0f}")
            print(f"  相对上日持仓变化率: {interpreted['oi_change_pct']*100:+.2f}%")
            print(f"  联动结构: {interpreted['regime']}")
            print(f"  交易信号: {interpreted['signal']}")
            print(f"  信号解读: {interpreted['signal_text']}")
            pd.DataFrame([interpreted]).to_csv(output_dir / "position_flow_realtime_snapshot.csv", index=False)
    except Exception as exc:
        print(f"\n  跳过实时持仓联动快照: {exc}")

    _save_latest_summary(
        output_dir,
        f"{_get_product_name(config.product)} 持仓-价格联动摘要",
        [
            f"- 日期: {_format_date(latest['trade_date'])}",
            f"- 主力合约: {latest['dominant_code']}",
            f"- 收盘价: {latest['close']:.2f}",
            f"- 当日涨跌: {latest['price_change']*100:+.2f}%",
            f"- 持仓变化: {latest['oi_change']:+.0f}",
            f"- 持仓变化率: {latest['oi_change_pct']*100:+.2f}%",
            f"- 联动结构: {latest['regime']}",
            f"- 交易信号: {latest['signal']}",
            f"- 信号解读: {latest['signal_text']}",
        ],
    )

    return analyzer


def _build_product_snapshot(config: ResearchConfig) -> Dict[str, str]:
    product_name = _get_product_name(config.product)
    ry_data, contracts_data = run_history(config)

    latest_ry = ry_data.sort_values("trade_date").iloc[-1]
    contracts_data = _augment_contracts_with_ths_latest(config, contracts_data)
    price_data = load_dominant_price(contracts_data)

    momentum = MomentumFactor()
    momentum_signal = momentum.generate_signals(momentum.calc_momentum(price_data))
    momentum_latest = momentum.summarize_latest(momentum_signal)

    macd = MACDFactor(denoise=config.denoise, smooth_window=config.smooth_window)
    macd_signal = macd.generate_signals(macd.calc_macd(price_data))
    macd_latest = macd.summarize_latest_trend(macd_signal)

    vr_factor = VirtualRealRatioFactor()
    dominant_data = load_dominant_contract_features(contracts_data)
    vr_data = vr_factor.calc_factor_values(dominant_data)
    vr_latest = vr_data.dropna(subset=["virtual_real_ratio"]).iloc[-1]

    flow_factor = PositionPriceFlowFactor()
    flow_data = flow_factor.calc_factor_values(load_dominant_contract_data(contracts_data))
    flow_latest = flow_data.dropna(subset=["price_change", "oi_change"]).iloc[-1]

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
        "持仓联动": str(flow_latest["regime"]),
        "持仓联动信号": str(flow_latest["signal"]),
        "持仓联动解读": str(flow_latest["signal_text"]),
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
    _print_header("多品种因子汇总页")
    summary_dir = config.output_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    snapshots = []
    products = _resolve_products("ALL" if config.product.upper() == DEFAULT_PRODUCT else config.product)
    for product in products:
        product_config = replace(config, product=product)
        snapshots.append(_build_product_snapshot(product_config))

    summary_df = pd.DataFrame(snapshots)
    summary_csv = summary_dir / "latest_factor_summary.csv"
    summary_df.to_csv(summary_csv, index=False)

    markdown_lines = [
        f"# 多品种因子汇总页",
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
        print(f"  持仓联动 / 信号: {snapshot['持仓联动']} / {snapshot['持仓联动信号']}")
        print(f"  持仓联动解读: {snapshot['持仓联动解读']}")

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
                f"- 持仓联动 / 信号: {snapshot['持仓联动']} / {snapshot['持仓联动信号']}",
                f"- 持仓联动解读: {snapshot['持仓联动解读']}",
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
        "roll_virtual_combo": "展期+虚实盘",
        "macd": "MACD",
        "position_price_flow": "持仓价格联动",
    }
    product_map = {code: meta["name"] for code, meta in PRODUCT_CONFIG.items()}
    colors = {"NI": "#1f2937", "SS": "#9c6644", "CU": "#2a9d8f"}

    abs_ic_path = output_dir / "factor_abs_ic5d_comparison.png"
    excess_path = output_dir / "factor_excess_return_comparison.png"

    factors = ["roll_yield", "momentum", "virtual_real_ratio", "roll_virtual_combo", "macd", "position_price_flow"]
    x = range(len(factors))
    width = 0.36

    fig, ax = plt.subplots(figsize=(11, 5))
    products = summary_df["product"].drop_duplicates().tolist()
    width = 0.8 / max(len(products), 1)
    for idx, product in enumerate(products):
        subset = summary_df[summary_df["product"] == product].set_index("factor")
        values = [subset.loc[factor, "abs_ic_5d"] * 100 for factor in factors]
        offset = idx - (len(products) - 1) / 2
        ax.bar([i + offset * width for i in x], values, width=width, label=product_map[product], color=colors.get(product, "#6b7280"))
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("|5日IC| (%)")
    ax.set_title("不同品种下各因子准确率对比（|5日IC|）")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(abs_ic_path, dpi=320)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    for idx, product in enumerate(products):
        subset = summary_df[summary_df["product"] == product].set_index("factor")
        values = [subset.loc[factor, "excess_return"] * 100 for factor in factors]
        offset = idx - (len(products) - 1) / 2
        ax.bar([i + offset * width for i in x], values, width=width, label=product_map[product], color=colors.get(product, "#6b7280"))
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("超额收益 (%)")
    ax.set_title("不同品种下各因子策略超额收益对比")
    ax.axhline(0, color="black", linewidth=1)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(excess_path, dpi=320)
    plt.close(fig)

    return {"abs_ic_chart": abs_ic_path, "excess_chart": excess_path}


def _compute_macd_metrics_for_config(config: ResearchConfig) -> List[Dict[str, object]]:
    product_name = _get_product_name(config.product)
    rows: List[Dict[str, object]] = []

    _, contracts_data = run_history(config)
    price_data = load_dominant_price(contracts_data)

    macd = MACDFactor(denoise=config.denoise, smooth_window=config.smooth_window)
    macd_signal = macd.generate_signals(macd.calc_macd(price_data))
    rows.append(_calc_macd_metrics(macd_signal, product_name, config.product))

    return rows


def _plot_denoise_comparison(summary_df: pd.DataFrame, output_dir: Path) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    factor_labels = {
        "macd": "MACD",
    }
    mode_labels = {"raw": "原始", "denoised": "降噪后"}
    colors = {"raw": "#9ca3af", "denoised": "#1f2937"}

    abs_ic_path = output_dir / "denoise_abs_ic5d_comparison.png"
    excess_path = output_dir / "denoise_excess_return_comparison.png"

    factors = ["macd"]
    x = range(len(factors))
    width = 0.36

    fig, ax = plt.subplots(figsize=(12, 5))
    for idx, mode in enumerate(["raw", "denoised"]):
        subset = summary_df[summary_df["mode"] == mode].set_index("factor")
        values = [subset.loc[factor, "abs_ic_5d"] * 100 for factor in factors]
        ax.bar([i + (idx - 0.5) * width for i in x], values, width=width, label=mode_labels[mode], color=colors[mode])
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("|5日IC| (%)")
    ax.set_title("降噪前后各因子准确率对比（|5日IC|）")
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(abs_ic_path, dpi=320)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5))
    for idx, mode in enumerate(["raw", "denoised"]):
        subset = summary_df[summary_df["mode"] == mode].set_index("factor")
        values = [subset.loc[factor, "excess_return"] * 100 for factor in factors]
        ax.bar([i + (idx - 0.5) * width for i in x], values, width=width, label=mode_labels[mode], color=colors[mode])
    ax.set_xticks(list(x))
    ax.set_xticklabels([factor_labels[f] for f in factors])
    ax.set_ylabel("超额收益 (%)")
    ax.set_title("降噪前后各因子超额收益对比")
    ax.axhline(0, color="black", linewidth=1)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(excess_path, dpi=320)
    plt.close(fig)

    return {"abs_ic_chart": abs_ic_path, "excess_chart": excess_path}


def run_denoise_compare(config: ResearchConfig) -> None:
    _print_header("降噪前后对比报告")

    products = _resolve_products("ALL" if config.product.upper() == DEFAULT_PRODUCT else config.product)
    factor_labels = {"macd": "MACD"}

    all_rows: List[Dict[str, object]] = []
    delta_rows: List[Dict[str, object]] = []

    for product in products:
        base_config = replace(config, product=product, denoise=False)
        denoised_config = replace(config, product=product, denoise=True)

        raw_rows = _compute_macd_metrics_for_config(base_config)
        denoised_rows = _compute_macd_metrics_for_config(denoised_config)

        for row in raw_rows:
            row["mode"] = "raw"
            all_rows.append(row)
        for row in denoised_rows:
            row["mode"] = "denoised"
            all_rows.append(row)

        raw_df = pd.DataFrame(raw_rows).set_index("factor")
        denoised_df = pd.DataFrame(denoised_rows).set_index("factor")
        for factor in raw_df.index:
            delta_rows.append(
                {
                    "product": product,
                    "product_name": _get_product_name(product),
                    "factor": factor,
                    "factor_label": factor_labels.get(factor, factor),
                    "raw_ic_5d": raw_df.loc[factor, "ic_5d"],
                    "denoised_ic_5d": denoised_df.loc[factor, "ic_5d"],
                    "delta_ic_5d": denoised_df.loc[factor, "ic_5d"] - raw_df.loc[factor, "ic_5d"],
                    "raw_abs_ic_5d": raw_df.loc[factor, "abs_ic_5d"],
                    "denoised_abs_ic_5d": denoised_df.loc[factor, "abs_ic_5d"],
                    "delta_abs_ic_5d": denoised_df.loc[factor, "abs_ic_5d"] - raw_df.loc[factor, "abs_ic_5d"],
                    "raw_excess_return": raw_df.loc[factor, "excess_return"],
                    "denoised_excess_return": denoised_df.loc[factor, "excess_return"],
                    "delta_excess_return": denoised_df.loc[factor, "excess_return"] - raw_df.loc[factor, "excess_return"],
                }
            )

    summary_df = pd.DataFrame(all_rows)
    delta_df = pd.DataFrame(delta_rows)

    output_dir = config.output_dir / "comparison" / "denoise"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / "denoise_comparison_raw.csv"
    delta_path = output_dir / "denoise_comparison_delta.csv"
    summary_df.to_csv(raw_path, index=False)
    delta_df.to_csv(delta_path, index=False)

    charts: Dict[str, Path] = {}
    if len(products) == 1:
        subset = summary_df[summary_df["product"] == products[0]].copy()
        charts = _plot_denoise_comparison(subset, output_dir)

    best_abs = delta_df.sort_values("delta_abs_ic_5d", ascending=False).iloc[0]
    best_return = delta_df.sort_values("delta_excess_return", ascending=False).iloc[0]

    markdown_lines = [
        "# 降噪前后对比报告",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 研究品种: {', '.join(products)}",
        f"- 平滑窗口: {config.smooth_window}",
        "",
        "## 核心结论",
        "",
        f"- |5日IC| 改善最多: {best_abs['product_name']} / {best_abs['factor_label']} / {best_abs['delta_abs_ic_5d']*100:+.2f}%",
        f"- 超额收益改善最多: {best_return['product_name']} / {best_return['factor_label']} / {best_return['delta_excess_return']*100:+.2f}%",
        "",
        "## 详细对比",
        "",
    ]

    for product in products:
        markdown_lines.extend([f"### {_get_product_name(product)}", ""])
        subset = delta_df[delta_df["product"] == product]
        for _, row in subset.iterrows():
            markdown_lines.append(
                f"- {row['factor_label']}: |5日IC| {row['raw_abs_ic_5d']*100:.2f}% -> {row['denoised_abs_ic_5d']*100:.2f}% "
                f"({row['delta_abs_ic_5d']*100:+.2f}%), 超额收益 {row['raw_excess_return']*100:+.2f}% -> "
                f"{row['denoised_excess_return']*100:+.2f}% ({row['delta_excess_return']*100:+.2f}%)"
            )
        markdown_lines.append("")

    if charts:
        markdown_lines.extend(
            [
                "## 输出文件",
                "",
                f"- 原始汇总: {raw_path}",
                f"- 差异汇总: {delta_path}",
                f"- |5日IC| 对比图: {charts.get('abs_ic_chart', '')}",
                f"- 超额收益对比图: {charts.get('excess_chart', '')}",
                "",
            ]
        )

    report_path = output_dir / "denoise_comparison_report.md"
    _write_text_file(report_path, "\n".join(markdown_lines).rstrip() + "\n")

    print(f"原始汇总已导出到: {raw_path}")
    print(f"差异汇总已导出到: {delta_path}")
    print(f"报告已导出到: {report_path}")
    if charts:
        print(f"图表已导出到: {charts}")


def run_compare(config: ResearchConfig) -> None:
    _print_header("品种影响对比回测")

    products = _resolve_products(config.product)
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

        combo_factor = RollVirtualComboFactor()
        combo_data = combo_factor.calc_factor_values(ry_data, vr_data)
        combo_analyzer = FactorICAnalyzer(
            factor_data=combo_data[["trade_date", "combo_score"]],
            price_data=combo_data[["trade_date", "close"]],
            factor_col="combo_score",
            factor_name="roll_virtual_combo",
            lower_factor_is_bullish=False,
        )
        rows.append(_calc_quant_factor_metrics("roll_virtual_combo", combo_analyzer, product_name, product))

        macd = MACDFactor()
        macd_signal = macd.generate_signals(macd.calc_macd(price_data))
        rows.append(_calc_macd_metrics(macd_signal, product_name, product))

        flow_factor = PositionPriceFlowFactor()
        flow_data = flow_factor.calc_factor_values(load_dominant_contract_data(contracts_data))
        flow_analyzer = FactorICAnalyzer(
            factor_data=flow_data[["trade_date", "position_flow_factor"]],
            price_data=flow_data[["trade_date", "close"]],
            factor_col="position_flow_factor",
            factor_name="position_price_flow",
            lower_factor_is_bullish=False,
        )
        rows.append(_calc_quant_factor_metrics("position_price_flow", flow_analyzer, product_name, product))

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


def run_commodity_vix_panic_reversion(config: ResearchConfig) -> pd.Series:
    _print_header(f"[VIX+{_get_product_name(config.product)}] 恐慌反转回测")

    from src.data_fetcher.fred_client import FredClient

    commodity_config = replace(config, product=config.product.upper())
    _, contracts_data = run_history(commodity_config)
    price_data = load_dominant_price(contracts_data)[["trade_date", "close"]].copy()

    fred = FredClient()
    vix_data = fred.get_series("VIXCLS", start_date=config.start_date, end_date=config.end_date)

    strategy = CommodityVIXPanicReversionStrategy(_get_product_name(config.product))
    merged = strategy.prepare_data(price_data, vix_data)
    signal_data = strategy.signal_generation(merged)
    portfolio = strategy.backtest(signal_data)
    summary = strategy.print_report(portfolio)

    output_dir = config.output_dir / f"{config.product.lower()}_vix_panic_reversion"
    paths = strategy.export_results(portfolio, output_dir)
    print(f"结果已导出到: {output_dir}/")
    print(f"导出文件: {paths}")
    return summary


def run_vix_compare(config: ResearchConfig) -> None:
    _print_header("VIX + RSI 三品种对比回测")

    products = _resolve_products("ALL" if config.product.upper() == DEFAULT_PRODUCT else config.product)
    rows: List[Dict[str, object]] = []

    from src.data_fetcher.fred_client import FredClient

    fred = FredClient()
    vix_data = fred.get_series("VIXCLS", start_date=config.start_date, end_date=config.end_date)

    for product in products:
        product_config = replace(config, product=product)
        _, contracts_data = run_history(product_config)
        price_data = load_dominant_price(contracts_data)[["trade_date", "close"]].copy()
        strategy = CommodityVIXPanicReversionStrategy(_get_product_name(product))
        merged = strategy.prepare_data(price_data, vix_data)
        signal_data = strategy.signal_generation(merged)
        portfolio = strategy.backtest(signal_data)
        summary = strategy.summarize(portfolio)

        rows.append(
            {
                "product": product,
                "product_name": _get_product_name(product),
                "strategy_total_return": summary["strategy_total_return"],
                "buy_hold_total_return": summary["buy_hold_total_return"],
                "excess_return": summary["strategy_total_return"] - summary["buy_hold_total_return"],
                "strategy_annualized_return": summary["strategy_annualized_return"],
                "strategy_sharpe": summary["strategy_sharpe"],
                "strategy_max_drawdown": summary["strategy_max_drawdown"],
                "trades": summary["trades"],
                "exposure": summary["exposure"],
            }
        )

    summary_df = pd.DataFrame(rows).sort_values("strategy_sharpe", ascending=False).reset_index(drop=True)
    comparison_dir = config.output_dir / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    summary_path = comparison_dir / "vix_strategy_product_comparison.csv"
    summary_df.to_csv(summary_path, index=False)

    chart_path = comparison_dir / "vix_strategy_product_comparison.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = {"NI": "#1f2937", "SS": "#9c6644", "CU": "#2a9d8f"}
    ax.bar(
        summary_df["product_name"],
        summary_df["excess_return"] * 100,
        color=[colors.get(p, "#6b7280") for p in summary_df["product"]],
    )
    ax.axhline(0, color="black", linewidth=1)
    ax.set_ylabel("超额收益 (%)")
    ax.set_title("VIX + RSI 商品策略三品种超额收益对比")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(chart_path, dpi=320)
    plt.close(fig)

    report_path = comparison_dir / "vix_strategy_product_comparison.md"
    markdown_lines = [
        "# VIX + RSI 三品种对比回测",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 核心结果",
        "",
    ]
    for _, row in summary_df.iterrows():
        markdown_lines.append(
            f"- {row['product_name']}: 策略收益 {row['strategy_total_return']*100:+.2f}%，"
            f"买入持有 {row['buy_hold_total_return']*100:+.2f}%，"
            f"超额收益 {row['excess_return']*100:+.2f}%，夏普 {row['strategy_sharpe']:.2f}"
        )
    markdown_lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- 汇总表: {summary_path}",
            f"- 图表: {chart_path}",
            "",
        ]
    )
    _write_text_file(report_path, "\n".join(markdown_lines))

    print("\n【核心对比】")
    print(f"  {'品种':<8} {'策略收益':>12} {'买入持有':>12} {'超额收益':>12} {'夏普':>8} {'最大回撤':>10}")
    print("  " + "-" * 72)
    for _, row in summary_df.iterrows():
        print(
            f"  {row['product_name']:<8} "
            f"{row['strategy_total_return']*100:>+11.2f}% "
            f"{row['buy_hold_total_return']*100:>+11.2f}% "
            f"{row['excess_return']*100:>+11.2f}% "
            f"{row['strategy_sharpe']:>7.2f} "
            f"{row['strategy_max_drawdown']*100:>+9.2f}%"
        )

    print(f"\nVIX策略对比汇总已导出到: {summary_path}")
    print(f"VIX策略对比报告已导出到: {report_path}")
    print(f"图表已导出到: {chart_path}")


def run_vix_compare_reverse(config: ResearchConfig) -> None:
    _print_header("反向 VIX + RSI 三品种对比回测")

    products = _resolve_products("ALL" if config.product.upper() == DEFAULT_PRODUCT else config.product)
    rows: List[Dict[str, object]] = []

    from src.data_fetcher.fred_client import FredClient

    fred = FredClient()
    vix_data = fred.get_series("VIXCLS", start_date=config.start_date, end_date=config.end_date)

    for product in products:
        product_config = replace(config, product=product)
        _, contracts_data = run_history(product_config)
        price_data = load_dominant_price(contracts_data)[["trade_date", "close"]].copy()
        strategy = CommodityVIXPanicReversionStrategy(_get_product_name(product), reverse=True)
        merged = strategy.prepare_data(price_data, vix_data)
        signal_data = strategy.signal_generation(merged)
        portfolio = strategy.backtest(signal_data)
        summary = strategy.summarize(portfolio)

        rows.append(
            {
                "product": product,
                "product_name": _get_product_name(product),
                "strategy_total_return": summary["strategy_total_return"],
                "buy_hold_total_return": summary["buy_hold_total_return"],
                "excess_return": summary["strategy_total_return"] - summary["buy_hold_total_return"],
                "strategy_annualized_return": summary["strategy_annualized_return"],
                "strategy_sharpe": summary["strategy_sharpe"],
                "strategy_max_drawdown": summary["strategy_max_drawdown"],
                "trades": summary["trades"],
                "exposure": summary["exposure"],
            }
        )

    summary_df = pd.DataFrame(rows).sort_values("strategy_sharpe", ascending=False).reset_index(drop=True)
    comparison_dir = config.output_dir / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    summary_path = comparison_dir / "vix_strategy_product_comparison_reverse.csv"
    summary_df.to_csv(summary_path, index=False)

    chart_path = comparison_dir / "vix_strategy_product_comparison_reverse.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    colors = {"NI": "#1f2937", "SS": "#9c6644", "CU": "#2a9d8f"}
    ax.bar(
        summary_df["product_name"],
        summary_df["excess_return"] * 100,
        color=[colors.get(p, "#6b7280") for p in summary_df["product"]],
    )
    ax.axhline(0, color="black", linewidth=1)
    ax.set_ylabel("超额收益 (%)")
    ax.set_title("反向 VIX + RSI 商品策略三品种超额收益对比")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(chart_path, dpi=320)
    plt.close(fig)

    report_path = comparison_dir / "vix_strategy_product_comparison_reverse.md"
    markdown_lines = [
        "# 反向 VIX + RSI 三品种对比回测",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 核心结果",
        "",
    ]
    for _, row in summary_df.iterrows():
        markdown_lines.append(
            f"- {row['product_name']}: 策略收益 {row['strategy_total_return']*100:+.2f}%，"
            f"买入持有 {row['buy_hold_total_return']*100:+.2f}%，"
            f"超额收益 {row['excess_return']*100:+.2f}%，夏普 {row['strategy_sharpe']:.2f}"
        )
    markdown_lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- 汇总表: {summary_path}",
            f"- 图表: {chart_path}",
            "",
        ]
    )
    _write_text_file(report_path, "\n".join(markdown_lines))

    print("\n【核心对比】")
    print(f"  {'品种':<8} {'策略收益':>12} {'买入持有':>12} {'超额收益':>12} {'夏普':>8} {'最大回撤':>10}")
    print("  " + "-" * 72)
    for _, row in summary_df.iterrows():
        print(
            f"  {row['product_name']:<8} "
            f"{row['strategy_total_return']*100:>+11.2f}% "
            f"{row['buy_hold_total_return']*100:>+11.2f}% "
            f"{row['excess_return']*100:>+11.2f}% "
            f"{row['strategy_sharpe']:>7.2f} "
            f"{row['strategy_max_drawdown']*100:>+9.2f}%"
        )

    print(f"\n反向VIX策略对比汇总已导出到: {summary_path}")
    print(f"反向VIX策略对比报告已导出到: {report_path}")
    print(f"图表已导出到: {chart_path}")


def run_all(config: ResearchConfig) -> None:
    _print_header(f"{_get_product_name(config.product)} 因子完整分析")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    _print_header("[1/10] 实时展期收益率表格")
    try:
        run_realtime(config)
    except Exception as exc:
        print(f"  跳过实时数据（需要同花顺API）: {exc}")

    _print_header("[2/10] 历史展期收益率计算")
    ry_data, contracts_data = run_history(config)

    _print_header("[3/10] 分位数阈值计算")
    run_threshold(config, ry_data)

    _print_header("[4/10] 因子IC分析")
    run_ic_analysis(config, ry_data, contracts_data)

    _print_header("[5/10] 价格动量因子")
    run_momentum_analysis(config, contracts_data)

    _print_header("[6/10] MACD 趋势分析")
    run_macd_analysis(config, contracts_data)

    _print_header("[7/10] 虚实盘比因子")
    run_virtual_ratio_analysis(config, contracts_data)

    _print_header("[8/10] 5分钟偏度因子")
    run_intraday_skew_analysis(config, contracts_data)

    _print_header("[9/10] 组合因子")
    run_roll_virtual_combo_analysis(config, ry_data, contracts_data)

    _print_header("[10/10] 持仓-价格联动因子")
    run_position_flow_analysis(config, contracts_data)

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
    print("  - intraday_skew/                  5分钟偏度因子结果")
    print("  - roll_virtual_combo/             展期+虚实盘组合因子结果")
    print("  - position_flow/                  持仓-价格联动因子结果")
    print("=" * 80 + "\n")


def run_all_products(config: ResearchConfig) -> None:
    _print_header("多品种完整分析")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    run_summary(replace(config, product="ALL"))

    for product in _resolve_products("ALL"):
        product_config = replace(config, product=product)
        _print_header(f"{_get_product_name(product)} 完整分析")
        run_all(product_config)

    _print_header("多品种输出完成")
    print(f"  汇总页: {config.output_dir / 'summary'}/")
    for product in _resolve_products("ALL"):
        print(f"  {_get_product_name(product)}结果: {config.output_dir / product.lower()}/")
    print("=" * 80 + "\n")


def run_pdf_report(config: ResearchConfig) -> Path:
    _print_header("[PDF] 综合总报告导出")

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

    pdf_path = export_comprehensive_report(product=product, output_dir=config.output_dir)
    print(f"综合总报告已导出到: {pdf_path}")
    return pdf_path


def run_factor_manual_pdf(config: ResearchConfig) -> Path:
    _print_header("[PDF] LaTeX 因子手册导出")
    try:
        pdf_path = export_factor_manual_latex(output_dir=config.output_dir)
        print(f"LaTeX 因子手册已导出到: {pdf_path}")
    except Exception as exc:
        print(f"LaTeX 导出失败，回退到原手册样式: {exc}")
        pdf_path = export_factor_manual_pdf(output_dir=config.output_dir)
        print(f"因子手册已导出到: {pdf_path}")
    return pdf_path


def run_signal_table(config: ResearchConfig) -> Path:
    _print_header("[图片] 指标信号总表导出")
    image_path = export_signal_table_image(product=config.product.upper(), output_dir=config.output_dir)
    print(f"指标信号总表已导出到: {image_path}")
    return image_path


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
    elif mode == "intraday_skew":
        _, contracts_data = run_history(config)
        run_intraday_skew_analysis(config, contracts_data)
    elif mode == "roll_virtual_combo":
        ry_data, contracts_data = run_history(config)
        run_roll_virtual_combo_analysis(config, ry_data, contracts_data)
    elif mode == "position_flow":
        _, contracts_data = run_history(config)
        run_position_flow_analysis(config, contracts_data)
    elif mode == "summary":
        run_summary(config)
    elif mode == "compare":
        run_compare(config)
    elif mode == "denoise_compare":
        run_denoise_compare(config)
    elif mode == "vix_panic":
        run_vix_panic_reversion(config)
    elif mode == "ni_vix_panic":
        run_nickel_vix_panic_reversion(config)
    elif mode == "commodity_vix_panic":
        run_commodity_vix_panic_reversion(config)
    elif mode == "vix_compare":
        run_vix_compare(config)
    elif mode == "vix_compare_reverse":
        run_vix_compare_reverse(config)
    elif mode == "pdf":
        run_pdf_report(config)
    elif mode == "manual_pdf":
        run_factor_manual_pdf(config)
    elif mode == "signal_table":
        run_signal_table(config)
    else:
        if mode == "all":
            run_all_products(replace(config, product="ALL"))
        elif config.product.upper() == "ALL":
            run_all_products(config)
        else:
            run_all(config)

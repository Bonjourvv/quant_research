"""商品版 VIX + RSI 恐慌反转回测模块。"""

from __future__ import annotations

from src.strategies.vix_panic_reversion import VIXPanicReversionStrategy


class CommodityVIXPanicReversionStrategy(VIXPanicReversionStrategy):
    """把 VIX + RSI 反转框架应用到商品主力连续。"""

    def __init__(self, product_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.underlying_name = f"{product_name}主力连续"
        self.chart_title = f"VIX + RSI {product_name}恐慌反转策略"

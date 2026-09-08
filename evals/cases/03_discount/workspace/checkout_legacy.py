"""已废弃的结算入口，仅保留用于历史订单兼容。"""


def legacy_order_total(prices: list[float]) -> float:
    return sum(prices)

from pricing import apply_discount


def order_total(prices: list[float], discount_percent: float = 0) -> float:
    return apply_discount(sum(prices), discount_percent)

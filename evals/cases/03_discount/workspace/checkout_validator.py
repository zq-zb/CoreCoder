"""结算参数校验，不参与订单价格计算。"""


def validate_checkout(prices: list[float]) -> bool:
    return all(price >= 0 for price in prices)

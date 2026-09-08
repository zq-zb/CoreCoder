"""订单报表格式化，不参与结算。"""


def render_order_total(total: float) -> str:
    return f"total={total:.2f}"

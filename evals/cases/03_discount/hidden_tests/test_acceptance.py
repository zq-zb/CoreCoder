from checkout import order_total
from pricing import apply_discount


def test_discount_keeps_callers_consistent():
    assert order_total([10, 20], 0) == 30
    assert order_total([50, 50], 25) == 75
    assert apply_discount(80, 50) == 40

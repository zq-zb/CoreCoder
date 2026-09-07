from checkout import order_total


def test_order_total_with_ten_percent_discount():
    assert order_total([40, 60], 10) == 90

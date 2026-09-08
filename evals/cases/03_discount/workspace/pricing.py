def apply_discount(subtotal: float, discount_percent: float) -> float:
    """Apply a percentage discount to a subtotal."""

    return subtotal - subtotal * discount_percent / 10

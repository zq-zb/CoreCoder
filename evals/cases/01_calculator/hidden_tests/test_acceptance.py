from calculator import add


def test_add_handles_signs_and_zero():
    assert add(-2, 3) == 1
    assert add(0, 0) == 0
    assert add(-4, -5) == -9

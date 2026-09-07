from ci_logs import extract_failures


def test_extracts_error_lines():
    assert extract_failures("ok\nERROR broken\ndone") == ["ERROR broken"]

from ci_logs import extract_failures


def test_supports_all_failure_markers_case_insensitively():
    logs = "ok\nfailed test_a\nTimeout after 5s\nerror: bad import\ndone"
    assert extract_failures(logs) == ["failed test_a", "Timeout after 5s", "error: bad import"]


def test_preserves_order_and_limit():
    logs = "ERROR first\nFAILED second\nTIMEOUT third"
    assert extract_failures(logs, limit=2) == ["ERROR first", "FAILED second"]

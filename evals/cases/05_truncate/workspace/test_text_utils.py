from text_utils import truncate


def test_truncate_long_text_respects_total_limit():
    result = truncate("abcdefghij", 7)
    assert result == "abcd..."
    assert len(result) == 7

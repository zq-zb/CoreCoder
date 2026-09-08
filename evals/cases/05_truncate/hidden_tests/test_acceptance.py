from text_utils import truncate


def test_truncate_preserves_short_text_and_handles_boundaries():
    assert truncate("abc", 5) == "abc"
    assert truncate("abc", 3) == "abc"
    assert truncate("abcdefgh", 6) == "abc..."
    assert len(truncate("中文内容过长", 5)) == 5

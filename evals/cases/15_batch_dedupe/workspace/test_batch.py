from batch import deduplicate


def test_removes_repeated_strings():
    assert deduplicate(["a", "a"]) == ["a"]

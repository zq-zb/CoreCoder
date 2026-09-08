from batch import deduplicate


def test_preserves_first_seen_order_without_mutation():
    source = ["deploy", "build", "test", "build"]
    assert deduplicate(source) == ["deploy", "build", "test"]
    assert source == ["deploy", "build", "test", "build"]


def test_supports_dictionary_tasks():
    first = {"repo": "a", "run": 1}
    second = {"repo": "b", "run": 2}
    assert deduplicate([first, second, dict(first)]) == [first, second]

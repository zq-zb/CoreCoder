from slug import slugify


def test_slugify_collapses_mixed_whitespace():
    assert slugify("  Hello   New\tWorld  ") == "hello-new-world"
    assert slugify("one\ntwo") == "one-two"
    assert slugify("") == ""

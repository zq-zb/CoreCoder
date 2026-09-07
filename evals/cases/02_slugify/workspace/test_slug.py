from slug import slugify


def test_slugify_simple_words():
    assert slugify("Hello World") == "hello-world"

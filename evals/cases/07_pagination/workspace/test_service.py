from api_client import Page
from service import collect_all


def test_collects_two_pages():
    pages = {None: Page(["a"], "next"), "next": Page(["b"], None)}
    assert collect_all(lambda token: pages[token]) == ["a", "b"]

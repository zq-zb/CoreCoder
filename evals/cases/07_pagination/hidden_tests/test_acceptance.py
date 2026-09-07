from api_client import Page
from service import collect_all


def test_empty_intermediate_page_does_not_end_pagination():
    pages = {
        None: Page(["a"], "empty"),
        "empty": Page([], "last"),
        "last": Page(["z"], None),
    }
    assert collect_all(lambda token: pages[token]) == ["a", "z"]

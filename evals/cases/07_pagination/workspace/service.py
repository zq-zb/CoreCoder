from api_client import Page


def collect_all(fetch_page) -> list[str]:
    items = []
    token = None
    while True:
        page: Page = fetch_page(token)
        if not page.items:
            break
        items.extend(page.items)
        token = page.next_token
        if token is None:
            break
    return items

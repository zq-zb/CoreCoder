from corecoder.prompt import system_prompt
from corecoder.tools import get_tool


def test_prompt_mentions_retrieval_only_when_tool_is_available() -> None:
    with_retrieval = system_prompt([get_tool("repository_search")])
    without_retrieval = system_prompt([get_tool("read_file")])

    assert "Retrieve before broad reading" in with_retrieval
    assert "Retrieve before broad reading" not in without_retrieval


def test_guided_prompt_explains_enforced_tool_order() -> None:
    prompt = system_prompt(
        [get_tool("repository_search"), get_tool("read_file")],
        repository_retrieval_policy="guided",
    )

    assert "Guided retrieval policy" in prompt
    assert "runtime enforces" in prompt

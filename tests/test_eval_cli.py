"""评测 CLI 默认只列出案例，避免误消耗真实 API。"""

from corecoder.eval_cli import _coding_tools, main


def test_eval_cli_lists_cases_without_calling_model(capsys):
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "已加载 16 个评测案例" in output
    assert "calculator-sign" in output
    assert "本次不调用付费模型" in output


def test_eval_cli_rejects_unknown_case():
    try:
        main(["--case", "missing-case"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("CLI 应该拒绝不存在的案例")


def test_eval_cli_rejects_invalid_repeat():
    try:
        main(["--repeat", "0"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("CLI 应该拒绝非正数重复次数")


def test_evaluation_prefers_dedicated_file_tools_over_bash():
    names = [tool.name for tool in _coding_tools()]

    assert names[:2] == ["read_file", "edit_file"]
    assert names[-1] == "bash"

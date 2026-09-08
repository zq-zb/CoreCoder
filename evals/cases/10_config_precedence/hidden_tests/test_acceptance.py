from config_merge import merge_config


def test_environment_has_highest_precedence():
    result = merge_config({"timeout": 10}, {"timeout": 20}, {"timeout": 30})
    assert result["timeout"] == 30


def test_none_does_not_erase_lower_priority_value():
    result = merge_config(
        {"timeout": 10, "model": "default"},
        {"timeout": None, "model": "file"},
        {"model": None},
    )
    assert result == {"timeout": 10, "model": "file"}

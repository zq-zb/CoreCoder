from config_merge import merge_config


def test_file_overrides_default():
    assert merge_config({"timeout": 10}, {"timeout": 20}, {})["timeout"] == 20

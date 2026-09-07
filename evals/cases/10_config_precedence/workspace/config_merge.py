def merge_config(defaults: dict, file_config: dict, env_config: dict) -> dict:
    result = dict(defaults)
    result.update(env_config)
    result.update(file_config)
    return result

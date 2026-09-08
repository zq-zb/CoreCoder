from retry_policy import should_retry


def test_server_error_retries_before_limit():
    assert should_retry(503, attempt=1, max_attempts=3) is True


def test_success_does_not_retry():
    assert should_retry(200, attempt=1, max_attempts=3) is False

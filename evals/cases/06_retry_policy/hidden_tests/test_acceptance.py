from retry_policy import should_retry


def test_rate_limit_retries():
    assert should_retry(429, attempt=0, max_attempts=2) is True


def test_client_error_does_not_retry():
    assert should_retry(400, attempt=0, max_attempts=2) is False


def test_attempt_at_limit_does_not_retry():
    assert should_retry(500, attempt=2, max_attempts=2) is False

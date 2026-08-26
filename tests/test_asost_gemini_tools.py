from types import SimpleNamespace

import pytest

from tools.asost_gemini_tools import _call_with_pool, classify_gemini_error


class ProviderError(Exception):
    def __init__(self, status_code=None, message="provider error", headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=headers or {})


class FakePool:
    def __init__(self, replacements=()):
        self.current = SimpleNamespace(id="good", runtime_api_key="good-key")
        self.replacements = list(replacements)
        self.marks = []
        self.refreshes = 0

    def peek(self):
        return self.current

    def try_refresh_current(self):
        self.refreshes += 1
        return None

    def mark_exhausted_and_rotate(self, **kwargs):
        self.marks.append(kwargs)
        return self.replacements.pop(0) if self.replacements else None


@pytest.mark.parametrize(
    ("status", "reason", "retryable", "credential_fault"),
    [
        (401, "auth", False, True),
        (403, "auth", False, True),
        (429, "rate_limit", True, True),
        (408, "timeout", True, False),
        (500, "server_error", True, False),
        (400, "format_error", False, False),
    ],
)
def test_gemini_classifier_categories(status, reason, retryable, credential_fault):
    result = classify_gemini_error(ProviderError(status))
    assert result.status_code == status
    assert result.failure_reason == reason
    assert result.retryable is retryable
    assert result.credential_fault is credential_fault


def test_rate_limit_passes_real_status_and_reset_to_pool():
    pool = FakePool()
    reset_at = 2_000_000_000

    with pytest.raises(ProviderError):
        _call_with_pool(
            pool,
            lambda _credential: (_ for _ in ()).throw(
                ProviderError(429, headers={"x-ratelimit-reset": str(reset_at)})
            ),
        )

    assert pool.marks[0]["status_code"] == 429
    assert pool.marks[0]["failure_reason"] == "rate_limit"
    assert pool.marks[0]["error_context"]["reset_at"] == reset_at


@pytest.mark.parametrize("status", [400, 408, 500])
def test_shared_failures_never_cool_down_a_healthy_credential(status):
    pool = FakePool()
    attempts = 0

    def fail(_credential):
        nonlocal attempts
        attempts += 1
        raise ProviderError(status)

    with pytest.raises(ProviderError):
        _call_with_pool(pool, fail)

    assert pool.marks == []
    assert attempts == (2 if status in {408, 500} else 1)


def test_content_rejection_403_is_not_treated_as_bad_credentials():
    pool = FakePool()
    with pytest.raises(ProviderError):
        _call_with_pool(
            pool,
            lambda _credential: (_ for _ in ()).throw(
                ProviderError(403, "responses cannot be generated due to safety")
            ),
        )
    assert pool.marks == []


def test_network_error_has_bounded_retry_without_pool_mutation():
    pool = FakePool()
    attempts = 0

    def fail(_credential):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("network is unreachable")

    with pytest.raises(ConnectionError):
        _call_with_pool(pool, fail)
    assert attempts == 2
    assert pool.marks == []


def test_local_error_fails_immediately_without_pool_mutation():
    pool = FakePool()
    with pytest.raises(ImportError):
        _call_with_pool(pool, lambda _credential: (_ for _ in ()).throw(ImportError()))
    assert pool.marks == []


def test_empty_response_retries_once_separately_then_escalates():
    pool = FakePool()
    attempts = 0

    def empty(_credential):
        nonlocal attempts
        attempts += 1
        return ""

    with pytest.raises(RuntimeError, match="empty response"):
        _call_with_pool(pool, empty)
    assert attempts == 2
    assert pool.marks == []

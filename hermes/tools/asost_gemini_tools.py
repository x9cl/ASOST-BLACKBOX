"""Gemini calls used by ASOST, with Hermes credential-pool semantics.

This module deliberately adapts :mod:`agent.error_classifier` rather than
maintaining a second list of Google error strings.  In particular, an HTTP
status is only one input to the decision: a 403 safety rejection is not an
authentication failure and an aggregator's upstream 429 is not a bad key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional, TypeVar

from agent.error_classifier import FailoverReason, classify_api_error


T = TypeVar("T")


@dataclass(frozen=True)
class GeminiFailure:
    """Pool-relevant projection of Hermes' provider error classification."""

    status_code: Optional[int]
    failure_reason: str
    retryable: bool
    credential_fault: bool
    reset_at: Optional[float]


_LOCAL_FATAL_ERRORS = (
    ImportError,
    ModuleNotFoundError,
    json.JSONDecodeError,
    AssertionError,
    AttributeError,
    NameError,
    SyntaxError,
    TypeError,
)


def _header(error: BaseException, name: str) -> Any:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    return headers.get(name) if hasattr(headers, "get") else None


def _timestamp(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return number / 1000 if number > 1_000_000_000_000 else number
    except (TypeError, ValueError):
        pass
    try:
        return parsedate_to_datetime(str(value)).timestamp()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None


def _reset_at(error: BaseException) -> Optional[float]:
    """Read Google's/HTTP's absolute reset metadata without inventing a TTL."""
    for value in (
        getattr(error, "reset_at", None),
        _header(error, "x-ratelimit-reset"),
        _header(error, "X-RateLimit-Reset"),
    ):
        parsed = _timestamp(value)
        if parsed is not None:
            return parsed

    retry_after = _header(error, "retry-after") or _header(error, "Retry-After")
    parsed = _timestamp(retry_after)
    if parsed is not None:
        # Small Retry-After numbers are delays, not Unix timestamps.
        if parsed < 100_000_000:
            import time

            return time.time() + parsed
        return parsed
    return None


def classify_gemini_error(error: Exception, *, model: str = "") -> GeminiFailure:
    """Project Hermes' canonical Gemini-aware verdict onto pool policy fields."""
    classified = classify_api_error(error, provider="gemini", model=model)
    credential_fault = classified.reason in {
        FailoverReason.auth,
        FailoverReason.auth_permanent,
        FailoverReason.billing,
        FailoverReason.rate_limit,
    } and classified.reason is not FailoverReason.upstream_rate_limit
    return GeminiFailure(
        status_code=classified.status_code,
        failure_reason=classified.reason.value,
        retryable=bool(classified.retryable),
        credential_fault=credential_fault,
        reset_at=_reset_at(error),
    )


def _is_empty_response(response: Any) -> bool:
    if response is None:
        return True
    if isinstance(response, str):
        return not response.strip()
    text = getattr(response, "text", None)
    return isinstance(text, str) and not text.strip()


def _mark_failed(pool: Any, failure: GeminiFailure, credential: Any) -> Any:
    context = {"reason": failure.failure_reason}
    if failure.reset_at is not None:
        context["reset_at"] = failure.reset_at
    kwargs = {
        "status_code": failure.status_code,
        "failure_reason": failure.failure_reason,
        "error_context": context,
    }
    credential_id = getattr(credential, "id", None)
    api_key = getattr(credential, "runtime_api_key", None)
    if credential_id:
        kwargs["credential_id"] = credential_id
    if api_key:
        kwargs["api_key_hint"] = api_key
    return pool.mark_exhausted_and_rotate(**kwargs)


def _call_with_pool(
    pool: Any,
    provider_call: Callable[[Any], T],
    *,
    model: str = "",
    transient_retries: int = 1,
) -> T:
    """Call a fake/real Gemini provider while mutating only culpable keys.

    Empty successful responses have their own one-retry budget.  408, 5xx and
    transport failures retry in place within ``transient_retries`` and never
    cool down a credential.  Auth and credential-scoped quota failures use the
    pool's established refresh/cooldown policy and carry the real HTTP status.
    """
    credential = pool.peek()
    transient_attempts = 0
    empty_retried = False

    while True:
        try:
            response = provider_call(credential)
        except _LOCAL_FATAL_ERRORS:
            raise
        except Exception as error:
            failure = classify_gemini_error(error, model=model)

            if failure.credential_fault:
                if failure.failure_reason in {"auth", "auth_permanent"}:
                    refreshed = pool.try_refresh_current()
                    if refreshed is not None:
                        credential = refreshed
                        continue
                replacement = _mark_failed(pool, failure, credential)
                # ``retryable`` describes retrying this credential/request.
                # A replacement credential is Hermes' recovery for terminal
                # auth/billing verdicts too, so do not gate rotation on it.
                if replacement is not None:
                    credential = replacement
                    continue
                raise

            # Shared request/content/schema errors and programming failures are
            # terminal. Crucially, neither path touches the healthy pool.
            if not failure.retryable:
                raise
            if transient_attempts >= transient_retries:
                raise
            transient_attempts += 1
            continue

        if not _is_empty_response(response):
            return response
        if empty_retried:
            raise RuntimeError("Gemini returned an empty response after one retry")
        empty_retried = True


__all__ = ["GeminiFailure", "classify_gemini_error", "_call_with_pool"]

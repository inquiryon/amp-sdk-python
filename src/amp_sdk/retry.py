"""Conservative retry policy (see oss-release/phase-5/sdk-compatibility-baseline.md
"Errors and retryability"). Retries are bounded by attempt count AND a
total timeout budget, use exponential backoff with jitter, and honor a
server-supplied Retry-After header when present.
"""

from __future__ import annotations

import email.utils
import random
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    """Total attempts including the first (not "retries")."""
    base_delay_s: float = 0.2
    max_delay_s: float = 5.0
    timeout_budget_s: float = 30.0
    """Total wall-clock budget across all attempts."""


DEFAULT_RETRY_POLICY = RetryPolicy()


def compute_backoff_s(attempt: int, policy: RetryPolicy) -> float:
    """Full jitter exponential backoff (AWS-style): random in [0, cappedDelay]."""
    exp = policy.base_delay_s * (2 ** max(0, attempt - 1))
    capped = min(exp, policy.max_delay_s)
    return random.uniform(0, capped)


def parse_retry_after_s(value: str | None) -> float | None:
    """Parse a Retry-After header: either delta-seconds or an HTTP-date."""
    if not value:
        return None
    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    delta = parsed.timestamp() - time.time()
    return delta if delta > 0 else 0.0


def is_retryable_status(status: int) -> bool:
    """HTTP-status-level retry classification for transport-received responses.

    Covers only "did we get a response, and should THAT status be
    retried" — auth/authz/validation/conflict statuses always return
    False here; callers additionally gate on operation-level idempotency
    safety (see client.py ``idempotent``).
    """
    if status == 429:
        return True
    return status in (502, 503, 504)

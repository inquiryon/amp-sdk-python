"""Typed error hierarchy for the AMP Python SDK.

Every error preserves: HTTP status (when there was an HTTP response), the
server's stable error ``code`` (when present), a message, the
request/correlation id (when the server supplied one), whether the SDK
considers the failure retryable, and bounded structured details.

None of these ever include the bearer token, the Authorization header, or
any other secret — the constructors only ever read from the parsed error
envelope, never from request headers.
"""

from __future__ import annotations

from typing import Any


class AmpError(Exception):
    """Base class for every error this SDK raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retryable = retryable
        self.details = details
        # Internal: the raw Retry-After header, when the failure was an
        # HTTP response. Not part of the public constructor signature —
        # set by client.py after construction, read back by the retry loop.
        self.retry_after_header: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (f"{type(self).__name__}(message={self.message!r}, status={self.status!r}, "
                f"code={self.code!r}, request_id={self.request_id!r}, retryable={self.retryable!r})")


class AuthenticationError(AmpError):
    """401 unauthenticated — missing or unknown bearer token. Never retried."""


class AuthorizationError(AmpError):
    """403 forbidden — authenticated but not authorized. Never retried."""


class NotFoundError(AmpError):
    """404 not_found. Never retried."""


class ConflictError(AmpError):
    """409 conflict — already decided differently, or an illegal transition. Never retried."""


class ValidationError(AmpError):
    """400/413/422 validation-family errors. Never retried — the request itself is wrong."""


class PolicyRejectedError(ValidationError):
    """422 invalid_policy — policy failed schema validation. ``details["errors"]`` holds the list."""


class ServerError(AmpError):
    """500 internal_error. Not retried by default (see the retry policy docs)."""


class TransportError(AmpError):
    """Connection-level failure: refused, reset, DNS failure, etc. No HTTP response was received."""

    def __init__(self, message: str, *, retryable: bool = True, cause: BaseException | None = None) -> None:
        super().__init__(message, retryable=retryable)
        self.__cause__ = cause


class TimeoutError_(AmpError):
    """The call did not complete within the configured timeout budget.

    Named with a trailing underscore to avoid shadowing the builtin
    ``TimeoutError``; re-exported as ``TimeoutError`` from the package
    ``__init__`` for ergonomics, since within this package's own namespace
    that shadowing is intentional and safe.
    """

    def __init__(self, message: str = "request timed out") -> None:
        super().__init__(message, retryable=False)


class CancellationError(AmpError):
    """The caller cancelled the call (cancel_event set)."""

    def __init__(self, message: str = "request was cancelled") -> None:
        super().__init__(message, retryable=False)


class UnsupportedVersionError(AmpError):
    """Client-synthesized only — the server never emits this code.

    Raised by ``check_version()`` when ``GET /version``'s ``contracts``
    field is not ``"v0"`` (see the compatibility baseline's "Version
    negotiation" section).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class MalformedResponseError(AmpError):
    """The server returned a 2xx response whose body could not be parsed as
    JSON, or whose JSON did not have the minimum expected shape.

    Distinct from ValidationError, which means the SERVER rejected the
    request; this means the SDK could not make sense of what the server
    sent back.
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message, retryable=False)
        self.__cause__ = cause


_STATUS_TO_ERROR = {
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    500: ServerError,
}


def error_from_envelope(status: int, envelope: Any) -> AmpError:
    """Map a parsed v0 ErrorEnvelope + HTTP status to a typed error."""
    err = envelope.get("error") if isinstance(envelope, dict) else None
    err = err if isinstance(err, dict) else {}
    code = err.get("code", "unknown_error")
    message = err.get("message") or f"request failed with HTTP {status}"
    request_id = err.get("request_id")
    details = err.get("details")

    if status == 422 and code == "invalid_policy":
        return PolicyRejectedError(message, status=status, code=code, request_id=request_id,
                                   details=details, retryable=False)
    if status in (400, 413, 422):
        return ValidationError(message, status=status, code=code, request_id=request_id,
                               details=details, retryable=False)
    cls = _STATUS_TO_ERROR.get(status)
    if cls is not None:
        return cls(message, status=status, code=code, request_id=request_id,
                   details=details, retryable=False)
    return ServerError(message, status=status, code=code, request_id=request_id,
                       details=details, retryable=False)

"""Low-level REST client: one HTTP call per method invocation, typed
errors, conservative retry, timeouts, cooperative cancellation.

Built on ``urllib.request`` (standard library only — see README.md "HTTP
dependency choice" for the deliberate zero-runtime-dependency tradeoff).
No governance-domain knowledge lives here; see ``governance.py`` for the
convenience façade.

Cancellation is cooperative, not preemptive: a ``threading.Event`` is
checked between retry attempts and during backoff waits. A single
in-flight blocking ``urlopen`` call cannot be interrupted mid-flight by
stdlib alone without a background thread; this is a deliberate, documented
limitation (see README.md), not an oversight.
"""

from __future__ import annotations

import json as json_module
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from .errors import (
    AmpError,
    CancellationError,
    MalformedResponseError,
    TimeoutError_,
    TransportError,
    error_from_envelope,
)
from .retry import (
    DEFAULT_RETRY_POLICY,
    RetryPolicy,
    compute_backoff_s,
    is_retryable_status,
    parse_retry_after_s,
)

SDK_VERSION = "0.1.0"
DEFAULT_USER_AGENT = f"inquiryon-amp-sdk-python/{SDK_VERSION}"

MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CHUNK = 64 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: raise the 3xx as an HTTPError instead of
    silently forwarding the Authorization header to a possibly different
    origin."""

    def redirect_request(self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any) -> None:
        return None


class RestClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 30.0,
        retry: RetryPolicy | None = None,
        user_agent: str | None = None,
        require_https_for_remote: bool = True,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        parsed = urllib.parse.urlsplit(base_url)
        if require_https_for_remote and parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"refusing to use plain HTTP against a non-loopback host ({parsed.hostname}); "
                "use https:// or pass require_https_for_remote=False to explicitly opt out "
                "for local/dev use")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._retry = retry or DEFAULT_RETRY_POLICY
        self._user_agent = f"{DEFAULT_USER_AGENT} {user_agent}" if user_agent else DEFAULT_USER_AGENT
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        timeout_s: float | None = None,
        idempotent: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        url = self._base_url + path
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                url = f"{url}?{urlencode(filtered)}"

        is_safe_method = method in ("GET", "HEAD")
        can_retry = is_safe_method or idempotent

        deadline = time.monotonic() + self._retry.timeout_budget_s
        last_error: AmpError | None = None

        for attempt in range(1, self._retry.max_attempts + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise CancellationError()
            if time.monotonic() >= deadline:
                break
            try:
                return self._attempt_once(method, url, body, timeout_s, cancel_event)
            except AmpError as err:
                last_error = err
                can_retry_this = can_retry and err.retryable and attempt < self._retry.max_attempts
                if not can_retry_this:
                    raise
                retry_after = parse_retry_after_s(err.retry_after_header)
                delay = retry_after if retry_after is not None else compute_backoff_s(attempt, self._retry)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sleep(min(delay, remaining), cancel_event)

        if last_error is not None:
            raise last_error
        raise TransportError("retry budget exhausted with no recorded error")

    @staticmethod
    def _sleep(seconds: float, cancel_event: threading.Event | None) -> None:
        if seconds <= 0:
            return
        if cancel_event is None:
            time.sleep(seconds)
            return
        if cancel_event.wait(seconds):
            raise CancellationError()

    def _attempt_once(
        self,
        method: str,
        url: str,
        body: Any,
        timeout_s: float | None,
        cancel_event: threading.Event | None,
    ) -> Any:
        effective_timeout = timeout_s if timeout_s is not None else self._timeout_s
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        data: bytes | None = None
        if body is not None:
            data = json_module.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with self._opener.open(req, timeout=effective_timeout) as resp:
                status = resp.status
                text = self._read_bounded(resp)
                retry_after_header = resp.headers.get("Retry-After")
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise MalformedResponseError(
                    f"server responded with a redirect (HTTP {exc.code}); this SDK never "
                    "follows redirects automatically to avoid silently forwarding the "
                    "Authorization header to another origin") from exc
            status = exc.code
            text = self._read_bounded(exc)
            retry_after_header = exc.headers.get("Retry-After") if exc.headers else None
        except TimeoutError as exc:
            # socket.timeout is a TimeoutError alias (Python >=3.10); on
            # 3.9 it is a distinct OSError subclass, handled below instead.
            if cancel_event is not None and cancel_event.is_set():
                raise CancellationError() from exc
            raise TimeoutError_(f"request timed out after {effective_timeout}s") from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise CancellationError() from exc
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(exc).lower():
                raise TimeoutError_(f"request timed out after {effective_timeout}s") from exc
            raise TransportError(
                f"transport failure calling {method} {url}: {exc}", cause=exc) from exc

        if status == 204 or not text:
            if status >= 400:
                err = error_from_envelope(status, {})
                self._attach_retry(err, status, retry_after_header)
                raise err
            return None

        try:
            parsed = json_module.loads(text)
        except json_module.JSONDecodeError as exc:
            raise MalformedResponseError(
                f"server response was not valid JSON (HTTP {status})", cause=exc) from exc

        if status >= 400:
            err = error_from_envelope(status, parsed)
            self._attach_retry(err, status, retry_after_header)
            raise err

        return parsed

    @staticmethod
    def _attach_retry(err: AmpError, status: int, retry_after_header: str | None) -> None:
        err.retryable = err.retryable or is_retryable_status(status)
        err.retry_after_header = retry_after_header

    @staticmethod
    def _read_bounded(resp: Any) -> str:
        declared = resp.headers.get("Content-Length") if resp.headers else None
        if declared is not None:
            try:
                if int(declared) > MAX_RESPONSE_BYTES:
                    raise MalformedResponseError(
                        f"response declared Content-Length {declared} exceeds the "
                        f"{MAX_RESPONSE_BYTES}-byte SDK limit")
            except ValueError:
                pass
        chunks = []
        total = 0
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise MalformedResponseError(
                    f"response body exceeded the {MAX_RESPONSE_BYTES}-byte SDK limit")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")

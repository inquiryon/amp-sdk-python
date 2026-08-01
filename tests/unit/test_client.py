from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.error
from typing import Any, Callable
from urllib.request import OpenerDirector

import pytest

from amp_sdk import (
    AmpClient,
    AuthenticationError,
    CancellationError,
    ConflictError,
    MalformedResponseError,
    NotFoundError,
    PolicyRejectedError,
    TimeoutError,
    TransportError,
    ValidationError,
)
from amp_sdk.client import RestClient


class _FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.status = status
        self.code = status
        self._body = body
        self._pos = 0
        self.headers = _Headers(headers or {})

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._body) - self._pos
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _FakeResponse:  # noqa: PYI034 - avoid a typing_extensions dep for `Self` on Python 3.9/3.10
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Headers:
    def __init__(self, data: dict[str, str]):
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key.lower(), default)


class FakeOpener(OpenerDirector):
    """Replaces the real network call; records every request seen."""

    def __init__(self, handler: Callable[[Any], _FakeResponse]):
        self._handler = handler
        self.requests: list[Any] = []

    def open(self, req: Any, data: Any = None, timeout: Any = None) -> _FakeResponse:  # type: ignore[override]
        self.requests.append(req)
        result = self._handler(req)
        if isinstance(result, _FakeResponse) and result.status >= 400:
            raise urllib.error.HTTPError(
                req.full_url, result.status, "err", result.headers,  # type: ignore[arg-type]
                io.BytesIO(result.read()))
        return result


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> _FakeResponse:
    return _FakeResponse(status, json.dumps(body).encode("utf-8"), headers)


def make_client(handler: Callable[[Any], _FakeResponse], **overrides: Any) -> RestClient:
    opener = FakeOpener(handler)
    kwargs: dict[str, Any] = {
        "retry": None,
        "opener": opener,
    }
    kwargs.update(overrides)
    client = RestClient("http://127.0.0.1:8080", "fictional-token-do-not-use", **kwargs)
    client._opener = opener  # type: ignore[attr-defined]
    return client


def test_token_only_sent_in_authorization_header() -> None:
    seen = {}

    def handler(req: Any) -> _FakeResponse:
        seen["auth"] = req.headers.get("Authorization")
        seen["ua"] = req.headers.get("User-agent")
        return json_response(200, {"status": "ok"})

    c = make_client(handler)
    c.request("GET", "/health")
    assert seen["auth"] == "Bearer fictional-token-do-not-use"
    assert "fictional-token-do-not-use" not in seen["ua"]


def test_401_maps_to_authentication_error_never_retried() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        return json_response(401, {"error": {"code": "unauthenticated", "message": "no"}})

    c = make_client(handler)
    with pytest.raises(AuthenticationError):
        c.request("GET", "/api/v0/me")
    assert calls["n"] == 1


def test_409_and_422_invalid_policy_map_correctly() -> None:
    c1 = make_client(lambda req: json_response(409, {"error": {"code": "conflict", "message": "x"}}))
    with pytest.raises(ConflictError):
        c1.request("POST", "/x")

    c2 = make_client(lambda req: json_response(
        422, {"error": {"code": "invalid_policy", "message": "bad", "details": {"errors": ["e1"]}}}))
    with pytest.raises(PolicyRejectedError) as exc_info:
        c2.request("PUT", "/api/v0/policies/p")
    assert exc_info.value.details == {"errors": ["e1"]}


def test_404_maps_to_not_found_error() -> None:
    c = make_client(lambda req: json_response(404, {"error": {"code": "not_found", "message": "no"}}))
    with pytest.raises(NotFoundError):
        c.request("GET", "/api/v0/policies/missing")


def test_get_retries_on_transport_failure_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return json_response(200, {"status": "ok"})

    c = make_client(handler)
    result = c.request("GET", "/health")
    assert result == {"status": "ok"}
    assert calls["n"] == 3


def test_post_without_idempotent_flag_is_never_retried() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        raise ConnectionError("boom")

    c = make_client(handler)
    with pytest.raises(TransportError):
        c.request("POST", "/api/v0/requests", body={})
    assert calls["n"] == 1


def test_post_with_idempotent_true_is_retried_on_transport_failure() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("boom")
        return json_response(200, {"request_id": "r1", "status": "allowed"})

    c = make_client(handler)
    result = c.request("POST", "/api/v0/requests", body={}, idempotent=True)
    assert result == {"request_id": "r1", "status": "allowed"}
    assert calls["n"] == 2


def test_422_is_never_retried_even_when_idempotent() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        return json_response(422, {"error": {"code": "validation_failed", "message": "bad"}})

    c = make_client(handler)
    with pytest.raises(ValidationError):
        c.request("POST", "/x", body={}, idempotent=True)
    assert calls["n"] == 1


def test_503_retried_for_safe_get_and_honors_retry_after() -> None:
    calls = {"n": 0}
    start = time.monotonic()

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] < 2:
            return json_response(503, {"error": {"code": "internal_error", "message": "busy"}},
                                 {"Retry-After": "0"})
        return json_response(200, {"status": "ok"})

    c = make_client(handler)
    c.request("GET", "/health")
    assert calls["n"] == 2
    assert time.monotonic() - start < 1.0


def test_timeout_raises_timeout_error_not_transport_error() -> None:
    def handler(req: Any) -> _FakeResponse:
        raise socket.timeout("timed out")

    c = make_client(handler)
    with pytest.raises(TimeoutError):
        c.request("GET", "/health")


def test_never_follows_redirect_automatically() -> None:
    def handler(req: Any) -> _FakeResponse:
        raise urllib.error.HTTPError(req.full_url, 302, "redirect",
                                     _Headers({"Location": "http://evil.example/"}), None)  # type: ignore[arg-type]

    c = make_client(handler)
    with pytest.raises(MalformedResponseError):
        c.request("GET", "/health")


def test_malformed_json_2xx_response_is_rejected_distinctly() -> None:
    def handler(req: Any) -> _FakeResponse:
        return _FakeResponse(200, b"not json", {"content-type": "application/json"})

    c = make_client(handler)
    with pytest.raises(MalformedResponseError):
        c.request("GET", "/health")


def test_refuses_plain_http_against_non_loopback_host_by_default() -> None:
    with pytest.raises(ValueError):
        RestClient("http://example.com", "t")


def test_cancellation_during_backoff_raises_cancellation_error() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        raise ConnectionError("boom")

    event = threading.Event()

    def canceller() -> None:
        time.sleep(0.05)
        event.set()

    threading.Thread(target=canceller, daemon=True).start()
    c = make_client(handler, retry=None)
    with pytest.raises((CancellationError, TransportError)):
        c.request("GET", "/health", cancel_event=event)


def test_ampclient_modify_sends_structured_params() -> None:
    seen: dict[str, Any] = {}

    def handler(req: Any) -> _FakeResponse:
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return json_response(200, {
            "hitl_id": "h1",
            "result": {"decision": "modified", "params": {"amount": 900},
                      "executed": True, "follow_up_hitl_id": None},
            "delivery_id": "d1", "delivered": True, "replayed": False,
        })

    client = AmpClient("http://127.0.0.1:8080", "t")
    client.rest = make_client(handler)
    outcome = client.modify("h1", {"amount": 900}, note="reduced")
    assert seen["body"] == {"decision": "modify", "modified_params": {"amount": 900}, "note": "reduced"}
    assert outcome.executed is True
    assert outcome.follow_up_review_id is None


def test_ampclient_wait_for_decision_polls_until_resolved() -> None:
    calls = {"n": 0}

    def handler(req: Any) -> _FakeResponse:
        calls["n"] += 1
        status = "pending" if calls["n"] < 3 else "modified"
        return json_response(200, {"request_id": "r1", "status": status})

    client = AmpClient("http://127.0.0.1:8080", "t")
    client.rest = make_client(handler)
    result = client.wait_for_decision("r1", interval_s=0.01, timeout_s=5)
    assert result["status"] == "modified"
    assert calls["n"] == 3


def test_ampclient_wait_for_decision_times_out() -> None:
    def handler(req: Any) -> _FakeResponse:
        return json_response(200, {"request_id": "r1", "status": "pending"})

    client = AmpClient("http://127.0.0.1:8080", "t")
    client.rest = make_client(handler)
    with pytest.raises(TimeoutError):
        client.wait_for_decision("r1", interval_s=0.01, timeout_s=0.03)


def test_unknown_response_fields_pass_through() -> None:
    def handler(req: Any) -> _FakeResponse:
        return json_response(200, {"request_id": "r1", "status": "allowed",
                                   "from_the_future": {"nested": True}})

    client = AmpClient("http://127.0.0.1:8080", "t")
    client.rest = make_client(handler)
    from amp_sdk.models import SubmitGovernedRequestInput
    out = client.submit_governed_request(
        SubmitGovernedRequestInput(policy_id="p", tool="t", action="a", request_id="r1"))
    assert out["status"] == "allowed"
    assert out["from_the_future"] == {"nested": True}  # type: ignore[typeddict-item]


def test_check_version_rejects_non_v0() -> None:
    from amp_sdk import UnsupportedVersionError

    def handler(req: Any) -> _FakeResponse:
        return json_response(200, {"name": "amp-community", "version": "9.9.9", "contracts": "v99"})

    client = AmpClient("http://127.0.0.1:8080", "t")
    client.rest = make_client(handler)
    with pytest.raises(UnsupportedVersionError):
        client.check_version()

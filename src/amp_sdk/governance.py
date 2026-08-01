"""Governance convenience façade over the low-level RestClient.

Every method here is a thin, direct mapping to one REST call (or, for
``wait_for_decision``, a bounded loop of one) — no hidden batching, no
client-side caching, no background threads started implicitly.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote

from .client import RestClient
from .errors import CancellationError, TimeoutError_, UnsupportedVersionError
from .models import (
    AuditEventDict,
    AuditQuery,
    DeliveryStatusDict,
    EvaluationResultDict,
    PolicyDict,
    RequestStatusDict,
    ResolveOutcome,
    ResolveResultDict,
    SubmitGovernedRequestInput,
    SubmitResultDict,
    VersionInfoDict,
    WorkitemDict,
)
from .retry import RetryPolicy


def _to_resolve_outcome(res: ResolveResultDict) -> ResolveOutcome:
    result = res.get("result", {})
    return ResolveOutcome(
        hitl_id=res["hitl_id"],
        decision=result["decision"],
        params=result.get("params"),
        executed=bool(result.get("executed", False)),
        follow_up_review_id=result.get("follow_up_hitl_id"),
        delivery_id=res["delivery_id"],
        delivered=res["delivered"],
        replayed=bool(res.get("replayed", False)),
        raw=res,
    )


class AmpClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 30.0,
        retry: RetryPolicy | None = None,
        user_agent: str | None = None,
        require_https_for_remote: bool = True,
    ) -> None:
        self.rest = RestClient(
            base_url, token,
            timeout_s=timeout_s, retry=retry, user_agent=user_agent,
            require_https_for_remote=require_https_for_remote,
        )

    # -- health/version -------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self.rest.request("GET", "/health")  # type: ignore[no-any-return]

    def get_version(self) -> VersionInfoDict:
        return self.rest.request("GET", "/version")  # type: ignore[no-any-return]

    def check_version(self) -> VersionInfoDict:
        """Opt-in client-side check: raises UnsupportedVersionError if the
        server's ``contracts`` field is not ``"v0"``. The server has no
        dedicated error code for this (see the compatibility baseline);
        this is a synthesized SDK-side guard, not a server contract."""
        info = self.get_version()
        if info.get("contracts") != "v0":
            raise UnsupportedVersionError(
                f'this SDK implements the "v0" contract baseline; '
                f'server reports "{info.get("contracts")}"')
        return info

    def me(self) -> dict[str, Any]:
        return self.rest.request("GET", "/api/v0/me")  # type: ignore[no-any-return]

    # -- policy lifecycle -------------------------------------------------

    def list_policies(self) -> dict[str, list[str]]:
        return self.rest.request("GET", "/api/v0/policies")  # type: ignore[no-any-return]

    def get_policy(self, policy_id: str) -> PolicyDict:
        return self.rest.request("GET", f"/api/v0/policies/{quote(policy_id, safe='')}")  # type: ignore[no-any-return]

    def import_policy(self, policy_id: str, policy: PolicyDict) -> dict[str, Any]:
        """Import/update a policy (reviewer role required server-side)."""
        return self.rest.request(  # type: ignore[no-any-return]
            "PUT", f"/api/v0/policies/{quote(policy_id, safe='')}", body=policy)

    def validate_policy(self, policy: PolicyDict, policy_id: str | None = None) -> dict[str, Any]:
        """Validate a policy document without storing it. The route's
        ``{policy_id}`` path segment exists for URL consistency with the
        other policy routes but the validate handler does not look it up
        or use it — validation runs purely against the request body. This
        defaults it to the policy's own ``policy_id`` (or a placeholder)
        so callers never have to think about it."""
        pid = policy_id or policy.get("policy_id") or "unvalidated"
        return self.rest.request(  # type: ignore[no-any-return]
            "POST", f"/api/v0/policies/{quote(pid, safe='')}/validate", body=policy)

    # -- evaluation and governed requests ----------------------------------

    def evaluate(
        self, policy_id: str, tool: str, action: str,
        params: dict[str, Any] | None = None,
        criteria_inputs: dict[str, Any] | None = None,
    ) -> EvaluationResultDict:
        return self.rest.request(  # type: ignore[no-any-return]
            "POST", f"/api/v0/policies/{quote(policy_id, safe='')}/evaluate",
            body={"tool": tool, "action": action, "params": params or {},
                  "criteria_inputs": criteria_inputs})

    def submit_governed_request(self, input: SubmitGovernedRequestInput) -> SubmitResultDict:
        """Submit a governed tool call. Strongly recommend passing
        ``request_id``: without one, this call is NOT automatically
        retried on transport failure (see the compatibility baseline's
        idempotency notes — only requests that reach human review are
        idempotent by request_id)."""
        return self.rest.request(  # type: ignore[no-any-return]
            "POST", "/api/v0/requests",
            idempotent=bool(input.request_id),
            body={
                "policy_id": input.policy_id, "tool": input.tool, "action": input.action,
                "params": input.params, "criteria_inputs": input.criteria_inputs,
                "request_id": input.request_id,
            })

    def get_request(self, request_id: str) -> RequestStatusDict:
        """Poll the decision for a request that reached human review.
        Raises NotFoundError if the request was allowed/denied
        synchronously (nothing to poll) or does not exist."""
        return self.rest.request("GET", f"/api/v0/requests/{quote(request_id, safe='')}")  # type: ignore[no-any-return]

    def wait_for_decision(
        self, request_id: str, *,
        interval_s: float = 1.0, timeout_s: float = 60.0,
        cancel_event: threading.Event | None = None,
    ) -> RequestStatusDict:
        """Optional polling helper: repeatedly calls get_request until the
        decision leaves "pending" or the timeout budget is exhausted. This
        is a convenience built entirely from public methods — callers may
        implement their own polling loop with get_request() directly
        instead."""
        deadline = time.monotonic() + timeout_s
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CancellationError()
            status = self.get_request(request_id)
            if status.get("status") != "pending":
                return status
            if time.monotonic() + interval_s > deadline:
                raise TimeoutError_(
                    f'request {request_id} did not leave "pending" within {timeout_s}s')
            if cancel_event is not None:
                if cancel_event.wait(interval_s):
                    raise CancellationError()
            else:
                time.sleep(interval_s)

    # -- HITL review lifecycle ---------------------------------------------

    def list_reviews(self) -> dict[str, list[WorkitemDict]]:
        return self.rest.request("GET", "/api/v0/hitl")  # type: ignore[no-any-return]

    def get_review(self, hitl_id: str) -> WorkitemDict:
        return self.rest.request("GET", f"/api/v0/hitl/{quote(hitl_id, safe='')}")  # type: ignore[no-any-return]

    def approve(self, hitl_id: str, note: str = "") -> ResolveOutcome:
        res: ResolveResultDict = self.rest.request(
            "POST", f"/api/v0/hitl/{quote(hitl_id, safe='')}/resolve",
            body={"decision": "approve", "note": note})
        return _to_resolve_outcome(res)

    def reject(self, hitl_id: str, note: str = "") -> ResolveOutcome:
        res: ResolveResultDict = self.rest.request(
            "POST", f"/api/v0/hitl/{quote(hitl_id, safe='')}/resolve",
            body={"decision": "reject", "note": note})
        return _to_resolve_outcome(res)

    def modify(self, hitl_id: str, modified_params: dict[str, Any], note: str = "") -> ResolveOutcome:
        """Structured modify. ``modified_params`` is required and must be a
        plain object — the server rejects a missing/null value (422)
        rather than silently executing an empty change (see the
        contract-compatibility report's Finding 1). ``executed=False``
        with a populated ``follow_up_review_id`` means the modification
        requires another review; it is NOT an error, and this method
        returns normally in that case."""
        res: ResolveResultDict = self.rest.request(
            "POST", f"/api/v0/hitl/{quote(hitl_id, safe='')}/resolve",
            body={"decision": "modify", "modified_params": modified_params, "note": note})
        return _to_resolve_outcome(res)

    # -- callback delivery --------------------------------------------------

    def get_delivery_status(self, delivery_id: str) -> DeliveryStatusDict:
        return self.rest.request("GET", f"/api/v0/callbacks/{quote(delivery_id, safe='')}")  # type: ignore[no-any-return]

    def retry_delivery(self, delivery_id: str) -> dict[str, Any]:
        """Retry exactly one delivery. Idempotent: safe to call on an
        already-delivered id."""
        return self.rest.request(  # type: ignore[no-any-return]
            "POST", f"/api/v0/callbacks/{quote(delivery_id, safe='')}/retry", idempotent=True)

    def retry_all_deliveries(self) -> dict[str, Any]:
        """Retry every currently-undelivered callback (reviewer role, bulk convenience)."""
        return self.rest.request("POST", "/api/v0/callbacks/retry", idempotent=True)  # type: ignore[no-any-return]

    # -- audit ----------------------------------------------------------------

    def list_audit_events(self, query: AuditQuery | None = None) -> dict[str, list[AuditEventDict]]:
        q = query or AuditQuery()
        return self.rest.request(  # type: ignore[no-any-return]
            "GET", "/api/v0/audit",
            query={"request_id": q.request_id, "event_type": q.event_type,
                   "since": q.since, "until": q.until, "limit": q.limit})

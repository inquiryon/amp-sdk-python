"""Shared live compatibility scenarios, run against a REAL amp-community
server (not a mock). See oss-release/phase-5/compat-scenarios.md in the
umbrella workspace for the scenario definitions this file implements —
the TypeScript SDK's test/compat/live.test.ts implements the identical
scenarios against the same contract. All data is fictional.

Run: pytest tests/compat -q  (requires amp-core/amp-community installed;
skips cleanly via conftest.py's importorskip if they are not).
"""

from __future__ import annotations

import threading
import time

import pytest

from amp_sdk import (
    AmpClient,
    AuthenticationError,
    CancellationError,
    ConflictError,
    RetryPolicy,
    TimeoutError,
    TransportError,
    ValidationError,
)
from amp_sdk.models import SubmitGovernedRequestInput

# Kept in sync with conftest.py's server-fixture token/policy constants
# (duplicated, not imported, to avoid relative-import packaging fragility
# in a plain pytest test-file layout).
REVIEWER_TOKEN = "fictional-reviewer-token-0001"
AGENT_TOKEN = "fictional-agent-token-0001"
VIEWER_TOKEN = "fictional-viewer-token-0001"
INVOICE_POLICY = {
    "policy_id": "invoice-governance",
    "schema_version": "v0",
    "action_governance": {
        "criteria": [{
            "criterion_id": "c-high-amount", "tool": "pay_invoice", "action": "*",
            "hardness": "hard",
            "evaluator": {"type": "compute", "formula": "amount > 1000"},
        }],
    },
}


def reviewer(base_url: str) -> AmpClient:
    return AmpClient(base_url, REVIEWER_TOKEN)


def agent(base_url: str) -> AmpClient:
    return AmpClient(base_url, AGENT_TOKEN)


# 1. health/version -----------------------------------------------------

def test_health_and_version(compat_server: str) -> None:
    c = reviewer(compat_server)
    assert c.health()["status"] == "ok"
    version = c.get_version()
    assert version["contracts"] == "v0"


# 2. authentication failure -----------------------------------------------

def test_authentication_failure(compat_server: str) -> None:
    bad = AmpClient(compat_server, "not-a-real-token")
    with pytest.raises(AuthenticationError) as exc_info:
        bad.me()
    assert exc_info.value.status == 401


# 3. policy import and retrieval -------------------------------------------

def test_policy_import_and_retrieval(compat_server: str) -> None:
    c = reviewer(compat_server)
    stored = c.import_policy("invoice-governance", INVOICE_POLICY)
    assert stored["stored"] is True
    fetched = c.get_policy("invoice-governance")
    assert fetched["action_governance"]["criteria"][0]["criterion_id"] == "c-high-amount"


# 4. policy validation -----------------------------------------------------

def test_policy_validation(compat_server: str) -> None:
    c = reviewer(compat_server)
    bad = c.validate_policy({"nonsense": True})  # type: ignore[arg-type]
    assert bad["valid"] is False
    assert bad["errors"]
    good = c.validate_policy(INVOICE_POLICY)
    assert good["valid"] is True


# 5. allow evaluation --------------------------------------------------------

def test_allow_evaluation(compat_server: str) -> None:
    c = reviewer(compat_server)
    c.import_policy("invoice-governance", INVOICE_POLICY)
    result = c.evaluate("invoice-governance", "pay_invoice", "submit", {"amount": 40})
    assert result["decision"] == "allow"


# 6. hard-policy failure ------------------------------------------------------

def test_hard_policy_failure_evaluation(compat_server: str) -> None:
    c = reviewer(compat_server)
    c.import_policy("invoice-governance", INVOICE_POLICY)
    result = c.evaluate("invoice-governance", "pay_invoice", "submit", {"amount": 5000})
    assert result["decision"] == "require_human"
    assert result["triggered_criteria"] == ["c-high-amount"]


# 7. human-review evaluation via submission ---------------------------------

def test_human_review_via_submission(compat_server: str) -> None:
    reviewer(compat_server).import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn7-0001"))
    assert out["status"] == "pending_review"
    assert out.get("hitl_id")


# 8. governed request submission (allow path) --------------------------------

def test_governed_request_allow_path(compat_server: str) -> None:
    reviewer(compat_server).import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 40}, request_id="req-scn8-0001"))
    assert out["status"] == "allowed"
    assert "hitl_id" not in out or not out.get("hitl_id")


# 9. idempotent submission replay --------------------------------------------

def test_idempotent_submission_replay(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    a = agent(compat_server)
    first = a.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn9-0001"))
    before = len(r.list_reviews()["items"])
    replay = a.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn9-0001"))
    assert replay["hitl_id"] == first["hitl_id"]
    assert replay.get("replayed") is True
    assert len(r.list_reviews()["items"]) == before


# 10. conflicting idempotency reuse -------------------------------------------

def test_conflicting_resolution_is_conflict_error(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn10-0001"))
    r.approve(out["hitl_id"])
    with pytest.raises(ConflictError) as exc_info:
        r.reject(out["hitl_id"])
    assert exc_info.value.status == 409
    review = r.get_review(out["hitl_id"])
    assert review["decision"]["decision"] == "approved"  # type: ignore[index]


# 11. decision polling ---------------------------------------------------------

def test_decision_polling(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn11-0001"))
    pending = agent(compat_server).get_request(out["request_id"])
    assert pending["status"] == "pending"
    r.approve(out["hitl_id"])
    resolved = agent(compat_server).get_request(out["request_id"])
    # RequestStatus.status reflects the WORKITEM lifecycle state, not the
    # decision verb: in poll-callback mode the callback "delivers"
    # synchronously and the workitem is immediately closed to "resumed" —
    # there is no observable window where status == "approved". The
    # decision verb itself is the separate `decision` field. This is a
    # real compatibility-report nuance (see
    # oss-release/phase-5/sdk-compatibility-baseline.md), not a server bug.
    assert resolved["status"] == "resumed"
    assert resolved["decision"] == "approved"
    assert resolved["executed_params"] == {"amount": 5000}


# 12. approve -------------------------------------------------------------------

def test_approve(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn12-0001"))
    outcome = r.approve(out["hitl_id"])
    assert outcome.decision == "approved"
    assert outcome.params == {"amount": 5000}
    assert outcome.delivery_id


# 13. reject ----------------------------------------------------------------------

def test_reject(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn13-0001"))
    outcome = r.reject(out["hitl_id"])
    assert outcome.decision == "rejected"
    assert outcome.params is None


# 14. valid structured modify ------------------------------------------------------

def test_valid_structured_modify(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn14-0001"))
    outcome = r.modify(out["hitl_id"], {"amount": 900})
    assert outcome.executed is True
    assert outcome.params == {"amount": 900}
    assert outcome.follow_up_review_id is None


# 15. malformed structured modify --------------------------------------------------

def test_malformed_structured_modify_rejected(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn15-0001"))
    with pytest.raises(ValidationError) as exc_info:
        r.rest.request("POST", f"/api/v0/hitl/{out['hitl_id']}/resolve", body={"decision": "modify"})
    assert exc_info.value.status == 422
    review = r.get_review(out["hitl_id"])
    assert review["status"] == "pending"


# 16. hard failure after modification ------------------------------------------------

def test_hard_failure_after_modification(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn16-0001"))
    outcome = r.modify(out["hitl_id"], {"amount": 99999})
    assert outcome.executed is False
    assert outcome.follow_up_review_id is not None


# 17. material-change re-review --------------------------------------------------------

def test_material_change_spawns_pending_follow_up(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn17-0001"))
    outcome = r.modify(out["hitl_id"], {"amount": 99999})
    follow_up = r.get_review(outcome.follow_up_review_id)  # type: ignore[arg-type]
    assert follow_up["status"] == "pending"
    assert follow_up["policy_id"] == "invoice-governance"


# 18. callback delivery status -----------------------------------------------------------

def test_callback_delivery_status(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn18-0001"))
    outcome = r.approve(out["hitl_id"])
    status = r.get_delivery_status(outcome.delivery_id)
    assert status["status"] == "delivered"
    assert status["attempts"] >= 1


# 19. callback retry -----------------------------------------------------------------------

def test_callback_retry_is_idempotent(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn19-0001"))
    outcome = r.approve(out["hitl_id"])
    retried = r.retry_delivery(outcome.delivery_id)
    assert retried["delivered"] is True


# 20. append-only audit query -----------------------------------------------------------------

def test_audit_query_is_append_only_and_ordered(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn20-0001"))
    r.approve(out["hitl_id"])
    from amp_sdk.models import AuditQuery
    events = r.list_audit_events(AuditQuery(request_id=out["request_id"]))["items"]
    types = [e["event_type"] for e in events]
    assert types[:4] == ["evaluation.completed", "decision.completed",
                        "hitl.requested", "hitl.pending"]
    assert "hitl.approved" in types
    for e in events:
        assert e["event_id"] and e["event_type"] and e["occurred_at"]


# 21. provider failure and safe fallback -------------------------------------------------------
# Not exercised live (the Community server's default provider does not
# crash). Covered by amp-community's own
# test_provider_failure_falls_back_safely_with_audit (amp-community/tests/test_api.py),
# which asserts the safety invariant at the composition seam directly —
# see compat-scenarios.md.


# 22. timeout ------------------------------------------------------------------------------------

def test_timeout_raises_timeout_error() -> None:
    # A real, deterministic socket-level timeout: a local TCP listener
    # that accepts the connection but never sends a byte back, using
    # stdlib transport exactly as the SDK does in production. Racing the
    # real compat_server's own (very fast, loopback) response time with a
    # tiny timeout is not reliable; an unroutable external address is not
    # deterministic across network/firewall environments either.
    import socket as socket_module

    listener = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept_and_hang() -> None:
        try:
            conn, _ = listener.accept()
            time.sleep(5)
            conn.close()
        except OSError:
            pass

    thread = threading.Thread(target=accept_and_hang, daemon=True)
    thread.start()
    try:
        c = AmpClient(f"http://127.0.0.1:{port}", REVIEWER_TOKEN, timeout_s=0.2,
                      retry=RetryPolicy(max_attempts=1, timeout_budget_s=1.0))
        with pytest.raises(TimeoutError):
            c.list_policies()
    finally:
        listener.close()


# 23. cancellation --------------------------------------------------------------------------------

def test_cancellation_of_wait_for_decision(compat_server: str) -> None:
    r = reviewer(compat_server)
    r.import_policy("invoice-governance", INVOICE_POLICY)
    out = agent(compat_server).submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id="req-scn23-0001"))
    cancel_event = threading.Event()
    threading.Timer(0.05, cancel_event.set).start()
    a = agent(compat_server)
    with pytest.raises(CancellationError):
        a.wait_for_decision(out["request_id"], interval_s=0.02, timeout_s=10,
                            cancel_event=cancel_event)


# 24. retry behavior --------------------------------------------------------------------------------

def test_retry_behavior_on_connection_refused(compat_server: str) -> None:
    # A closed local port: connection refused on every attempt.
    c = AmpClient("http://127.0.0.1:1", REVIEWER_TOKEN,
                  retry=RetryPolicy(max_attempts=3, base_delay_s=0.01,
                                    max_delay_s=0.02, timeout_budget_s=2.0))
    with pytest.raises(TransportError):
        c.submit_governed_request(SubmitGovernedRequestInput(
            policy_id="p", tool="t", action="a", request_id="req-scn24-0001"))


# 25. unknown response fields ----------------------------------------------------------------------
# The live server does not currently emit undocumented extra fields (see
# compat-scenarios.md); the forward-compatible-parsing property itself is
# exercised at the unit level (test_unknown_response_fields_pass_through).
# This live test only confirms every real response above parsed without
# raising, which all prior scenarios in this file already demonstrate.


# 26. unsupported schema/API version -----------------------------------------------------------------

def test_check_version_accepts_the_real_server(compat_server: str) -> None:
    c = reviewer(compat_server)
    info = c.check_version()  # must not raise against the real v0 server
    assert info["contracts"] == "v0"
    # The raising branch (a server reporting something other than "v0")
    # cannot be produced by the real, correctly-functioning server; it is
    # covered at the unit level instead (test_check_version_rejects_non_v0
    # in tests/unit).


# 27. malformed server response -----------------------------------------------------------------------
# Not reproducible against the real, correctly-functioning server; covered
# at the unit level (test_malformed_json_2xx_response_is_rejected_distinctly).

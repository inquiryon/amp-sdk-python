"""Audit-history query: the complete, append-only event trail for one
governed request. Fictional data only."""

from __future__ import annotations

from _shared import agent_client, ensure_policy, new_request_id, reviewer_client

from inquiryon_amp_sdk.models import AuditQuery, SubmitGovernedRequestInput


def main() -> None:
    ensure_policy()
    agent = agent_client()
    reviewer = reviewer_client()

    submitted = agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id=new_request_id("audit")))
    reviewer.approve(submitted["hitl_id"], note="ok to pay")

    events = reviewer.list_audit_events(AuditQuery(request_id=submitted["request_id"]))["items"]
    for event in events:
        print(f'{event["occurred_at"]}  {event["event_type"]:<20} actor={event["actor"]}')


if __name__ == "__main__":
    main()

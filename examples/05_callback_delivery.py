"""Callback-delivery handling: after a review is resolved, the server
records a durable delivery attempt (stable delivery_id, visible status,
idempotent retry) instead of a fire-and-forget notification. Fictional
data only."""

from __future__ import annotations

from _shared import agent_client, ensure_policy, new_request_id, reviewer_client

from amp_sdk.models import SubmitGovernedRequestInput


def main() -> None:
    ensure_policy()
    agent = agent_client()
    reviewer = reviewer_client()

    submitted = agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id=new_request_id("callback")))
    outcome = reviewer.approve(submitted["hitl_id"])
    print("resolved with delivery_id:", outcome.delivery_id, "delivered:", outcome.delivered)

    status = reviewer.get_delivery_status(outcome.delivery_id)
    print("delivery status:", status["status"], "attempts:", status["attempts"])

    # Retrying an already-delivered id is safe (idempotent) — useful after a
    # transient failure without needing to re-decide the review.
    retried = reviewer.retry_delivery(outcome.delivery_id)
    print("retry result:", retried)


if __name__ == "__main__":
    main()

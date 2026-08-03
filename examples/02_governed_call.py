"""A governed tool call: the agent submits, and either gets an immediate
decision or a pending review depending on policy. Fictional data only."""

from __future__ import annotations

from _shared import agent_client, ensure_policy, new_request_id

from inquiryon_amp_sdk.models import SubmitGovernedRequestInput


def main() -> None:
    ensure_policy()
    agent = agent_client()

    small = agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 40}, request_id=new_request_id("small")))
    print("small invoice:", small["status"])  # "allowed" — safe to execute immediately

    large = agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id=new_request_id("large")))
    print("large invoice:", large["status"], "hitl_id=", large.get("hitl_id"))
    # -> "pending_review": a human reviewer must approve/reject/modify
    # (see 04_approve_reject_modify.py) before the agent should execute it.


if __name__ == "__main__":
    main()

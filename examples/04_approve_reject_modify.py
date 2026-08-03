"""Approve, reject, and structured modify — the three review resolutions.
Fictional data only."""

from __future__ import annotations

from _shared import agent_client, ensure_policy, new_request_id, reviewer_client

from inquiryon_amp_sdk.models import SubmitGovernedRequestInput


def submit(agent, amount: int, tag: str):
    return agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": amount}, request_id=new_request_id(tag)))


def main() -> None:
    ensure_policy()
    agent = agent_client()
    reviewer = reviewer_client()

    # Approve: execute exactly as submitted.
    to_approve = submit(agent, 5000, "approve")
    approved = reviewer.approve(to_approve["hitl_id"], note="verified vendor")
    print("approved:", approved.decision, approved.params)

    # Reject: nothing executes.
    to_reject = submit(agent, 6000, "reject")
    rejected = reviewer.reject(to_reject["hitl_id"], note="suspicious invoice")
    print("rejected:", rejected.decision, rejected.params)  # params is None

    # Modify: a structured replacement, re-evaluated before executing.
    to_modify = submit(agent, 5000, "modify")
    modified = reviewer.modify(to_modify["hitl_id"], {"amount": 900}, note="reduced to policy limit")
    print("modified (within limit, executes):", modified.executed, modified.params)

    # Modify that still fails the hard policy: never executes, spawns a
    # follow-up review instead of an error.
    to_modify_again = submit(agent, 5000, "modify-still-blocked")
    still_blocked = reviewer.modify(to_modify_again["hitl_id"], {"amount": 99999})
    print("modified (still over limit, does not execute):",
          still_blocked.executed, "follow-up review:", still_blocked.follow_up_review_id)


if __name__ == "__main__":
    main()

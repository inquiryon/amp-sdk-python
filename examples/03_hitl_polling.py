"""HITL polling: an agent submits a request that requires review, then
waits for a human decision using the optional wait_for_decision helper.
In a real deployment, the "reviewer resolves" step below would happen
from a separate process/person using the worktray UI or their own
approve/reject/modify call — it is inlined here (on a background thread)
only so the example is runnable end-to-end without a second terminal.
Fictional data only."""

from __future__ import annotations

import threading
import time

from _shared import agent_client, ensure_policy, new_request_id, reviewer_client

from inquiryon_amp_sdk.models import SubmitGovernedRequestInput


def main() -> None:
    ensure_policy()
    agent = agent_client()
    reviewer = reviewer_client()

    submitted = agent.submit_governed_request(SubmitGovernedRequestInput(
        policy_id="invoice-governance", tool="pay_invoice", action="submit",
        params={"amount": 5000}, request_id=new_request_id("poll")))
    print("submitted, awaiting review:", submitted["hitl_id"])

    def approve_after_delay() -> None:
        time.sleep(0.5)
        reviewer.approve(submitted["hitl_id"])
        print("(reviewer approved in the background)")

    threading.Thread(target=approve_after_delay, daemon=True).start()

    decision = agent.wait_for_decision(submitted["request_id"], interval_s=0.2, timeout_s=10)
    print("final status:", decision["status"], "decision:", decision.get("decision"),
          "executed_params:", decision.get("executed_params"))


if __name__ == "__main__":
    main()

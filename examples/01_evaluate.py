"""Basic policy evaluation: dry-run a tool call against a policy without
creating a request or review. Fictional data only."""

from __future__ import annotations

from _shared import ensure_policy, reviewer_client


def main() -> None:
    ensure_policy()
    client = reviewer_client()

    allowed = client.evaluate("invoice-governance", "pay_invoice", "submit", {"amount": 40})
    print("amount=40  ->", allowed["decision"], allowed["reason"])

    blocked = client.evaluate("invoice-governance", "pay_invoice", "submit", {"amount": 5000})
    print("amount=5000 ->", blocked["decision"], blocked["reason"],
          "triggered:", blocked.get("triggered_criteria"))


if __name__ == "__main__":
    main()

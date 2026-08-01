"""Shared setup for the examples in this directory. Fictional data only."""

from __future__ import annotations

import os
import random
import time

from amp_sdk import AmpClient

BASE_URL = os.environ.get("AMP_BASE_URL", "http://127.0.0.1:8080")
REVIEWER_TOKEN = os.environ.get("AMP_REVIEWER_TOKEN", "fictional-reviewer-token-0001")
AGENT_TOKEN = os.environ.get("AMP_AGENT_TOKEN", "fictional-agent-token-0001")

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


def reviewer_client() -> AmpClient:
    return AmpClient(BASE_URL, REVIEWER_TOKEN)


def agent_client() -> AmpClient:
    return AmpClient(BASE_URL, AGENT_TOKEN)


def ensure_policy() -> None:
    reviewer_client().import_policy("invoice-governance", INVOICE_POLICY)


def new_request_id(prefix: str) -> str:
    return f"req-{prefix}-{int(time.time() * 1000)}-{random.randint(0, 999)}"

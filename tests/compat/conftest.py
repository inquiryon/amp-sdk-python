"""Spins up a real amp-community server in-process (not mocked HTTP) for
the shared live compatibility scenarios (oss-release/phase-5/compat-scenarios.md).

Requires amp-core and amp-community to be importable — install them from
the umbrella workspace: `pip install -e ../amp-core -e ../amp-community`.
Skips the whole compat suite cleanly if they are not available, so the
unit suite (tests/unit) never depends on this.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, Iterator

import pytest

amp_community = pytest.importorskip(
    "amp_community", reason="amp-community is not installed; "
    "run `pip install -e ../amp-core -e ../amp-community` from the umbrella workspace")

from amp_community.api import build_api_context  # noqa: E402
from amp_community.api.server import start_background  # noqa: E402

REVIEWER_TOKEN = "fictional-reviewer-token-0001"
AGENT_TOKEN = "fictional-agent-token-0001"
VIEWER_TOKEN = "fictional-viewer-token-0001"

INVOICE_POLICY: Dict[str, Any] = {
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


@pytest.fixture()
def compat_server() -> Iterator[str]:
    tmp = tempfile.mkdtemp(prefix="amp-sdk-python-compat-")
    config = {
        "db_path": os.path.join(tmp, "amp.db"),
        "policy_dir": os.path.join(tmp, "policies"),
        "callback": {"mode": "poll"},
        "tokens": [
            {"token": REVIEWER_TOKEN, "principal": "alice", "role": "reviewer"},
            {"token": AGENT_TOKEN, "principal": "agent:invoice-agent", "role": "service"},
            {"token": VIEWER_TOKEN, "principal": "victor", "role": "viewer"},
        ],
    }
    ctx = build_api_context(config)
    httpd, port = start_background(ctx)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()

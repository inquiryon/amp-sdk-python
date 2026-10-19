# amp-sdk-python examples

All examples use fictional data (`invoice-governance`, `pay_invoice`,
fictional tokens) and run against a local `amp-community` server. None of
this touches a real production system.

## 1. Start a local amp-community server

Install `amp-community` from PyPI into its own virtualenv:

```bash
python3 -m venv .venv-server && .venv-server/bin/pip install inquiryon-amp-community
cat > /tmp/amp-example-config.json <<'EOF'
{
  "db_path": "/tmp/amp-example.db",
  "policy_dir": "/tmp/amp-example-policies",
  "port": 8080,
  "callback": { "mode": "poll" },
  "tokens": [
    { "token": "fictional-reviewer-token-0001", "principal": "alice", "role": "reviewer" },
    { "token": "fictional-agent-token-0001", "principal": "agent:invoice-agent", "role": "service" }
  ]
}
EOF
.venv-server/bin/python -m inquiryon_amp_community.api --config /tmp/amp-example-config.json
```

Leave that running. In a second terminal:

## 2. Install the SDK and set environment variables

```bash
git clone https://github.com/inquiryon/amp-sdk-python.git && cd amp-sdk-python
python3 -m venv .venv && .venv/bin/pip install inquiryon-amp-sdk
export AMP_BASE_URL=http://127.0.0.1:8080
export AMP_REVIEWER_TOKEN=fictional-reviewer-token-0001
export AMP_AGENT_TOKEN=fictional-agent-token-0001
```

## 3. Run an example

```bash
.venv/bin/python examples/01_evaluate.py
.venv/bin/python examples/02_governed_call.py
.venv/bin/python examples/03_hitl_polling.py
.venv/bin/python examples/04_approve_reject_modify.py
.venv/bin/python examples/05_callback_delivery.py
.venv/bin/python examples/06_audit_query.py
```

Each example imports a fresh copy of the `invoice-governance` policy, so
they can be run in any order or repeated.

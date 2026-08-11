# amp-sdk-python

Python SDK for the AMP Community governance API: policy evaluation,
governed tool-call submission, human-in-the-loop (HITL) review, callback
delivery, and audit-history queries.

Implements the `v0` API contract. See
[the versioning policy](#versioning-policy) before depending on this in
production, and [Publication status](#publication-status) for install
instructions.

## What this SDK is

A small, typed client for the `amp-community` REST API (the "SDK
compatibility boundary" served at `/api/v0/openapi.json`). It exposes
exactly the operations documented in that OpenAPI contract: evaluate a
policy, submit a governed request, poll or wait for a decision,
list/approve/reject/modify HITL reviews, check/retry callback delivery,
and query the audit log.

## What this SDK is not

- **Not** a client for any Enterprise-only capability: RLHF/training,
  model promotion, proprietary scoring, billing, organizations, SaaS
  auth, or private analytics. None of these exist in the public contract,
  so there is nothing here to call.
- **Not** an agent runtime. This package makes HTTP calls and returns
  typed results; it does not manage agent processes or background polling
  beyond the one opt-in `wait_for_decision` helper.

## Supported Python versions

CPython **>= 3.9**.

## Install

```bash
pip install inquiryon-amp-sdk
```

(Not yet published to PyPI — see [Publication status](#publication-status).
Until then, install from a local path or wheel: `pip install -e
../amp-sdk-python` or `pip install ./inquiryon_amp_sdk-0.1.0-py3-none-any.whl`.)

## HTTP dependency choice

This package has **zero runtime dependencies** — it uses
`urllib.request`/`http.client` from the standard library, not `httpx` or
`requests`. This is a deliberate tradeoff, not an oversight:

- This SDK is a low-volume governance-API client (submit a request, wait
  for a human decision, query an audit log), not a high-throughput
  data-plane client — the connection-pooling and HTTP/2 benefits of
  `httpx`/`requests` are not meaningfully needed here.
- This project's other packages already establish a minimal-dependency
  norm: `amp-core` has zero dependencies; `amp-community` has exactly one
  (`jsonschema`, added for schema-validation correctness, not convenience).
- Retry, backoff, timeout, and redirect-refusal logic (see below) is
  hand-rolled either way — a third-party HTTP client would not remove that
  complexity from this codebase, only add supply-chain surface.

If a genuine need for connection pooling or HTTP/2 emerges under real
usage, revisiting this in favor of `httpx` (MIT-licensed, sync+async with
one API) would be a `0.x` minor addition, not a breaking change — see the
versioning policy.

**Async client**: not included in this initial release. `urllib.request`
is synchronous-only, and no current integration requires async I/O — OSS-006
explicitly permits deferring an async client until "justified by first
integrations." Adding one later (most likely via `httpx.AsyncClient`,
opt-in) is additive, not breaking.

**Cancellation note**: cancellation via `cancel_event` (a
`threading.Event`) is cooperative, checked between retry attempts and
during backoff waits — a single in-flight blocking `urlopen` call cannot
be interrupted mid-flight by the standard library alone without a
background thread. This is a deliberate, documented limitation.

## Quickstart

```python
import os
from inquiryon_amp_sdk import AmpClient
from inquiryon_amp_sdk.models import SubmitGovernedRequestInput

client = AmpClient(
    "http://127.0.0.1:8080",
    os.environ["AMP_TOKEN"],  # never hardcode a real token
)

# Import a policy (reviewer role required server-side).
client.import_policy("invoice-governance", {
    "policy_id": "invoice-governance",
    "schema_version": "v0",
    "action_governance": {
        "criteria": [{
            "criterion_id": "c-high-amount", "tool": "pay_invoice", "action": "*",
            "hardness": "hard",
            "evaluator": {"type": "compute", "formula": "amount > 1000"},
        }],
    },
})

# Submit a governed tool call. Always pass a request_id for safe retries.
submitted = client.submit_governed_request(SubmitGovernedRequestInput(
    policy_id="invoice-governance", tool="pay_invoice", action="submit",
    params={"amount": 5000}, request_id="req-fictional-0001"))

if submitted["status"] == "pending_review":
    # ... a reviewer later calls client.approve/reject/modify(submitted["hitl_id"]) ...
    decision = client.wait_for_decision(submitted["request_id"], timeout_s=60)
    print(decision["status"], decision.get("executed_params"))
```

See `examples/` for complete, runnable programs (policy evaluation, a
governed tool call, HITL polling, approve/reject/modify, callback-delivery
handling, and an audit-history query) using only fictional data.

## Errors

Every failure is a typed subclass of `AmpError` carrying the HTTP status
(when applicable), the server's stable error code, the correlation
`request_id` (when the server supplied one), whether the SDK considers it
retryable, and bounded structured details:

```python
from inquiryon_amp_sdk import NotFoundError

try:
    client.get_review("hitl-does-not-exist")
except NotFoundError as err:
    print(err.status, err.code)
```

See `src/inquiryon_amp_sdk/errors.py` for the complete, exact mapping from server
error code to SDK error type and retry classification.

## Retries and idempotency

GET requests are retried automatically (bounded exponential backoff with
jitter, honoring `Retry-After`, within a total timeout budget). Mutations
are retried automatically **only** when they are transport failures for an
operation the caller has marked idempotent — `submit_governed_request` when
a `request_id` was supplied, or a delivery retry (idempotent by
construction). A received 4xx response is never retried. See the baseline
document for the full policy and its rationale.

## Security notes

- The bearer token is only ever sent in the `Authorization` header — never
  logged, never placed in the `User-Agent` string, never included in an
  error message.
- HTTPS is required for any non-loopback base URL by default (opt out
  explicitly with `require_https_for_remote=False` for deliberate
  local/dev use only).
- This client never follows an HTTP redirect automatically — a 3xx
  response is surfaced as an error rather than silently forwarding the
  Authorization header to a possibly different origin.
- Response bodies are capped at 10 MiB; no telemetry is collected or sent
  anywhere by default.

## Versioning policy

This package is `0.1.0`, tracking the `v0` API contract.
During `0.x`, any change to request/response shapes, error classification,
or retry semantics may ship in a minor version and will be called out
under **Breaking** in `CHANGELOG.md`. **No v1.0 stability is declared or
implied by this package.**

## Publication status

**Implementation complete; publication pending.** This package builds and
tests reproducibly locally (see `CONTRIBUTING.md`) but has not been
published to PyPI, and no GitHub repository has been created for it — see
`workitems/OSS-006-sdks-and-examples.md` in the umbrella workspace for the
exact gates remaining before publication.

## License

Apache-2.0 — see `LICENSE` and `NOTICE`.

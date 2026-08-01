# Contributing to amp-sdk-python

Thanks for your interest in contributing.

## Developer Certificate of Origin (DCO)

Every commit must be signed off, certifying you wrote the change or
otherwise have the right to submit it under this project's license
(Apache-2.0):

```
git commit -s -m "your message"
```

This adds a `Signed-off-by: Your Name <you@example.com>` trailer. PRs with
unsigned commits will be asked to amend before merge.

## Development setup

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m mypy
.venv/bin/python -m ruff check src tests examples
.venv/bin/python -m pytest tests/unit -q
```

The live compatibility suite (`pytest tests/compat -q`) requires
`amp-core`/`amp-community` installed (`pip install -e ../amp-core -e
../amp-community`) and is primarily a CI gate. CI checks out and imports
both source packages explicitly, then treats any installation, startup, or
scenario failure as blocking. Contributors running only the unit suite do
not need the sibling packages.

## Before opening a PR

- `mypy` and `ruff check` pass with no errors.
- `pytest tests/unit -q` passes locally.
- `python -m build` succeeds and the wheel/sdist contents match the
  package-content checklist in the README (no test files, no caches, no
  secrets).
- New public API surface is documented in the relevant docstrings and,
  for behavior changes, in `CHANGELOG.md`.
- No secrets, production URLs, or non-fictional identifiers appear
  anywhere in the diff, including tests and examples.

## Scope

This SDK intentionally implements a small, stable governance API (see
`oss-release/phase-5/sdk-compatibility-baseline.md` in the umbrella
workspace). PRs that add Enterprise-only concepts, platform-specific
filesystem/polling behavior, or hidden telemetry will not be accepted —
see the project's `README.md` "What this SDK is not" section.

## Reporting bugs vs. security issues

Functional bugs: open a GitHub issue. Security vulnerabilities: see
`SECURITY.md` — do not open a public issue.

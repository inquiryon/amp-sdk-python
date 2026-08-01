# Security Policy

## Reporting a vulnerability

Please report suspected security vulnerabilities privately to
**team@inquiryon.com**. Do not open a public GitHub issue for suspected
vulnerabilities.

Include:

- a description of the issue and its potential impact;
- steps to reproduce (a minimal fictional example is ideal);
- the SDK version and Python version in use.

We will acknowledge receipt within 5 business days and aim to provide a
remediation timeline within 10 business days of confirming the issue.

## Supported versions

This package is `0.x` (experimental v0 contract). Only the latest `0.x`
release receives security fixes; there is no long-term-support branch at
this stage. See `CHANGELOG.md` for the version history.

## Scope

In scope: the SDK's own code (`src/amp_sdk/`) — request signing/transport,
retry/idempotency logic, error handling, and anything that could leak a
credential, follow an unintended redirect, or mishandle an untrusted
server response.

Out of scope: the `amp-community` server itself (report separately, same
contact), and vulnerabilities requiring a modified/patched copy of this
package.

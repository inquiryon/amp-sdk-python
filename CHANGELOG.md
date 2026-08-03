# Changelog

All notable changes to this project are documented in this file. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is `0.x`: minor versions may contain breaking changes, always
called out below under an explicit **Breaking** heading (see the
versioning policy in `README.md`'s "Versioning policy" section).

## [0.1.0] — Unreleased

Initial release. Implements the `v0` Community governance API contract.

### Added

- `RestClient`: low-level typed HTTP client (`urllib.request`, zero
  runtime dependencies; bearer auth, conservative retry with bounded
  exponential backoff + jitter + `Retry-After`, timeout, cooperative
  cancellation via `threading.Event`, redirect-refusal, response-size cap,
  malformed-JSON handling).
- `AmpClient`: governance convenience façade — `evaluate`,
  `submit_governed_request`, `get_request`, `wait_for_decision`,
  `list_reviews`, `get_review`, `approve`, `reject`, `modify`,
  `get_delivery_status`, `retry_delivery`, `retry_all_deliveries`,
  `list_audit_events`, and policy lifecycle methods (`list_policies`,
  `get_policy`, `import_policy`, `validate_policy`).
- Typed error hierarchy: `AuthenticationError`, `AuthorizationError`,
  `NotFoundError`, `ConflictError`, `ValidationError`,
  `PolicyRejectedError`, `ServerError`, `TransportError`, `TimeoutError`,
  `CancellationError`, `UnsupportedVersionError`, `MalformedResponseError`.
- Typed models (`TypedDict` for permissive response shapes, `dataclass`
  for request-construction conveniences) for every v0 wire shape, with the
  five distinct decision/status vocabularies kept as separate types (see
  the compatibility report).
- `py.typed` marker (PEP 561).

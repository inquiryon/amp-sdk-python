"""Typed request/response models for the AMP Community v0 governance API.

Five decision/status vocabularies are DISTINCT and must never be conflated:
EvaluationDecisionValue, SubmitStatus, ResolveDecisionInput,
ResolvedDecisionValue, WorkitemStatus.

Response shapes are ``TypedDict`` with ``total=False`` on optional keys —
this is a static-only construct; at runtime a plain ``dict`` may carry any
extra keys the server adds in the future without this SDK crashing or
dropping them (the "safe handling of unknown response fields" requirement).
Request-construction conveniences use small ``dataclasses`` instead, for a
better typed calling experience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

EvaluationDecisionValue = Literal["allow", "deny", "require_human"]
"""Dry-run/internal evaluation outcome. Never conflate with SubmitStatus."""

SubmitStatus = Literal["allowed", "denied", "pending_review"]
"""Outcome of POST /api/v0/requests. Never conflate with EvaluationDecisionValue."""

ResolveDecisionInput = Literal["approve", "reject", "modify"]
"""Input to POST /api/v0/hitl/{id}/resolve. Imperative form."""

ResolvedDecisionValue = Literal["approved", "rejected", "modified"]
"""Output of a resolve call. Past-tense form; distinct type from the input."""

WorkitemStatus = Literal[
    "pending", "approved", "rejected", "modified",
    "resumed", "closed", "expired", "cancelled",
]
"""Full HITL workitem lifecycle."""

DeliveryStatusValue = Literal["pending", "delivered", "failed"]


class PolicyCriterionDict(TypedDict, total=False):
    criterion_id: str
    tool: str
    action: str
    hardness: Literal["hard", "soft"]
    condition_semantics: Literal["block_when", "allow_when"]
    text: str
    description: str
    evaluator: dict[str, Any]


class PolicyDict(TypedDict, total=False):
    policy_id: str
    schema_version: Literal["v0"]
    allow_unknown_tools: bool
    action_governance: dict[str, Any]


class CriterionResultDict(TypedDict, total=False):
    criterion_id: str
    hardness: Literal["hard", "soft"]
    evaluator_type: Literal["compute", "llm", "hybrid", "input"]
    status: Literal["met", "not_met"]
    condition_semantics: Literal["block_when", "allow_when"]
    condition_met: bool
    triggered: bool
    reason: str
    trigger_reason: str


class EvaluationResultDict(TypedDict, total=False):
    decision: EvaluationDecisionValue
    reason: str
    triggered_criteria: list[str]
    soft_triggered: list[str]
    criteria_results: list[CriterionResultDict]


class SubmitResultDict(TypedDict, total=False):
    request_id: str
    status: SubmitStatus
    reason: str
    hitl_id: str
    replayed: bool


class WorkitemDict(TypedDict, total=False):
    hitl_id: str
    request_id: str
    tool: str
    action: str
    params: dict[str, Any]
    reason: str
    triggered_criteria: list[str]
    status: WorkitemStatus
    requested_by: str
    scope: str | None
    policy_id: str | None
    created_at: str
    decision: dict[str, Any] | None


class ResolveResultDict(TypedDict, total=False):
    hitl_id: str
    result: dict[str, Any]
    delivery_id: str
    delivered: bool
    replayed: bool


class RequestStatusDict(TypedDict, total=False):
    request_id: str
    hitl_id: str
    status: str
    decision: str | None
    executed_params: dict[str, Any] | None
    follow_up_hitl_id: str | None


class AuditEventDict(TypedDict, total=False):
    event_id: str
    event_type: str
    occurred_at: str
    request_id: str
    actor: str
    scope: str | None
    payload: dict[str, Any]


class DeliveryStatusDict(TypedDict, total=False):
    delivery_id: str
    hitl_id: str
    request_id: str
    status: DeliveryStatusValue
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str


class VersionInfoDict(TypedDict, total=False):
    name: str
    version: str
    contracts: str


@dataclass
class SubmitGovernedRequestInput:
    policy_id: str
    tool: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    criteria_inputs: dict[str, Any] | None = None
    request_id: str | None = None
    """Idempotency key. Strongly recommended — see the compatibility
    baseline's "Idempotency" section: without one, a retried submission is
    not automatically retried by this SDK on transport failure."""


@dataclass
class ResolveOutcome:
    """Convenience-layer shape returned by AmpClient.approve/reject/modify."""

    hitl_id: str
    decision: ResolvedDecisionValue
    params: dict[str, Any] | None
    executed: bool
    follow_up_review_id: str | None
    delivery_id: str
    delivered: bool
    replayed: bool
    raw: ResolveResultDict


@dataclass
class AuditQuery:
    request_id: str | None = None
    event_type: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int | None = None
    """Server default is 200 when omitted."""

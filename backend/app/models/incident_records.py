"""Persistent incident records for the OPSYN operator workflow.

An :class:`IncidentRecord` is the backend-owned history entry for one
operator-injected fault and the agent run that investigated it. It is
*metadata about the run* — it never flows into the agent's reasoning:
the agent's own ``Incident`` keeps ``fault_type=None`` and only ever sees
observable tool results. Storing ``injected_fault_type`` here is safe
because this record is read by the operator UI and the evaluator, never
by the reasoning model.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

# Lifecycle. INJECTED -> INVESTIGATING -> REMEDIATING -> VERIFYING ->
# RESOLVED, with FAILED / UNRESOLVED as terminal non-resolved outcomes.
STATUS_INJECTED = "INJECTED"
STATUS_INVESTIGATING = "INVESTIGATING"
STATUS_REMEDIATING = "REMEDIATING"
STATUS_VERIFYING = "VERIFYING"
STATUS_RESOLVED = "RESOLVED"
STATUS_FAILED = "FAILED"
STATUS_UNRESOLVED = "UNRESOLVED"

TERMINAL_STATUSES = frozenset({STATUS_RESOLVED, STATUS_FAILED, STATUS_UNRESOLVED})

_STAGE_ORDER = (
    STATUS_INJECTED,
    STATUS_INVESTIGATING,
    STATUS_REMEDIATING,
    STATUS_VERIFYING,
    STATUS_RESOLVED,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StageEvent(BaseModel):
    """One lifecycle transition with a real timestamp."""

    model_config = ConfigDict(extra="ignore")

    stage: str = Field(description="Lifecycle stage reached")
    at: datetime = Field(default_factory=_now)


class IncidentRecord(BaseModel):
    """One persisted incident: injection metadata + agent trace summary."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str = Field(description="Canonical record ID, e.g. INC-2026-001")
    agent_incident_id: str | None = Field(
        default=None,
        description="ID of the agent-run Incident this record tracks",
    )
    service: str = Field(default="payment-api")
    title: str = Field(
        default="Payment API experiencing elevated failures",
        description="Symptom-based until resolved; diagnosis only after verification",
    )
    injected_fault_type: str | None = Field(
        default=None,
        description="Simulator fault that was injected (operator metadata only)",
    )
    status: str = Field(default=STATUS_INJECTED)
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = Field(default=None)
    current_stage: str = Field(default=STATUS_INJECTED)
    stage_history: list[StageEvent] = Field(default_factory=list)
    detected_symptoms: list[str] = Field(default_factory=list)
    diagnosis: str | None = Field(default=None)
    selected_action: str | None = Field(default=None)
    action_result: str | None = Field(default=None)
    verification_result: dict[str, object] = Field(default_factory=dict)
    recalled_memory_count: int = Field(default=0)
    recalled_memory_ids: list[str] = Field(default_factory=list)
    learning_outcome: str | None = Field(default=None)
    learning_lesson: str | None = Field(default=None)
    suitable_for_hindsight: bool = Field(default=False)
    # Full agent trace (hypotheses / investigation / actions / verification /
    # learning) as plain data, so the details view needs no second source.
    trace: dict[str, object] = Field(default_factory=dict)

    def mark_stage(self, stage: str) -> None:
        """Advance lifecycle, appending a timestamped history entry."""
        self.current_stage = stage
        self.status = stage
        self.stage_history.append(StageEvent(stage=stage, at=_now()))
        if stage in TERMINAL_STATUSES:
            self.resolved_at = _now()

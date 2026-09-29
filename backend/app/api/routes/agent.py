"""Agent API: run the deterministic incident-response agent.

Evaluation harness only: callers may optionally name a ``fault_type``
to inject into the payment simulator before the run. Agent-facing
responses never include hidden simulator state.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.dependencies import (
    get_incident_response_agent,
    get_incident_store,
    get_payment_simulator,
)
from app.models.incident import Incident, IncidentSource
from app.models.incident_records import (
    STATUS_FAILED,
    STATUS_INVESTIGATING,
    STATUS_REMEDIATING,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    STATUS_VERIFYING,
)
from app.services.agent import IncidentResponseAgent
from app.services.incident_store import IncidentStore
from app.services.payment_simulator import FAULTS, PaymentSimulator, UnknownFaultError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    incident_id: str | None = Field(default=None)
    service: str = Field(default="payment-api")
    fault_type: str | None = Field(default=None)
    symptoms: list[str] = Field(default_factory=list)
    incident_record_id: str | None = Field(
        default=None,
        description=(
            "Existing record (from POST /api/incidents) to attach this run "
            "to instead of creating a new one."
        ),
    )


@router.get("/tools")
async def agent_tools() -> dict[str, object]:
    from app.services.agent_tools import ACTION_TOOLS, OBSERVATION_TOOLS

    return {
        "observation_tools": list(OBSERVATION_TOOLS),
        "action_tools": list(ACTION_TOOLS),
    }


@router.post("/run")
async def agent_run(
    payload: AgentRunRequest,
    agent: IncidentResponseAgent = Depends(get_incident_response_agent),
    simulator: PaymentSimulator = Depends(get_payment_simulator),
    store: IncidentStore = Depends(get_incident_store),
) -> dict[str, object]:
    if payload.fault_type is not None:
        if payload.fault_type not in FAULTS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown fault: {payload.fault_type}",
            )
        try:
            simulator.inject_fault(payload.fault_type)
        except UnknownFaultError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc
    incident = Incident(
        incident_id=payload.incident_id or "SIM-agent-run",
        service=payload.service,
        environment="production",
        source=IncidentSource.SIMULATOR,
        fault_type=None,  # never copy harness metadata into agent state
        symptoms=list(payload.symptoms) or ["agent-initiated investigation"],
    )
    logger.info("INCIDENT_STARTED via API incident=%s", incident.incident_id)

    # Operator-side incident record. The injected fault is stored as
    # metadata only — the agent Incident above stays clean and the
    # reasoning model never receives it.
    record = None
    if payload.incident_record_id is not None:
        record = store.get(payload.incident_record_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown incident record: {payload.incident_record_id}",
            )
        if payload.fault_type is not None and record.injected_fault_type is None:
            store.update(record.incident_id, injected_fault_type=payload.fault_type)
            record = store.get(record.incident_id)
    else:
        record = store.create(
            service=payload.service,
            injected_fault_type=(
                payload.fault_type if payload.fault_type in FAULTS else None
            ),
            agent_incident_id=incident.incident_id,
            detected_symptoms=list(incident.symptoms),
        )
    assert record is not None
    record_id = record.incident_id

    def on_stage(stage: str, context: dict[str, object]) -> None:
        # Lifecycle mirror only: INVESTIGATING / REMEDIATING / VERIFYING
        # plus small observable summaries. Never touches agent state.
        if stage == STATUS_INVESTIGATING:
            store.mark_stage(record_id, STATUS_INVESTIGATING)
            store.update(
                record_id,
                recalled_memory_count=int(context.get("recalled_memory_count", 0) or 0),
                recalled_memory_ids=list(context.get("recalled_memory_ids", []) or []),
            )
        elif stage in (STATUS_REMEDIATING, STATUS_VERIFYING):
            updated = store.mark_stage(record_id, stage)
            if stage == STATUS_REMEDIATING and updated is not None:
                action = context.get("action")
                if isinstance(action, str) and not updated.selected_action:
                    store.update(record_id, selected_action=action)

    try:
        result = await agent.run(incident, on_stage=on_stage)
    except Exception:
        store.mark_stage(record_id, STATUS_FAILED)
        store.update(record_id, learning_outcome="error")
        raise
    _finalize_record(store, record_id, result)
    learning = result.learning
    return {
        "incident_id": result.incident_id,
        "incident_record_id": record_id,
        "outcome": learning.outcome if learning else None,
        "hypotheses": [h.model_dump() for h in result.hypotheses],
        "investigation": [s.model_dump(mode="json") for s in result.investigation],
        "actions": [a.model_dump(mode="json") for a in result.actions],
        "verification": result.verification.model_dump() if result.verification else None,
        "learning": learning.model_dump() if learning else None,
        "incident": result.model_dump(mode="json"),
    }


def _finalize_record(store: IncidentStore, record_id: str, result: Incident) -> None:
    """Write terminal state + full trace from the finished agent run."""
    learning = result.learning
    outcome = learning.outcome if learning else None
    if outcome == "resolved":
        terminal = STATUS_RESOLVED
    elif outcome in ("escalated", "unresolved"):
        terminal = STATUS_UNRESOLVED
    else:
        terminal = STATUS_FAILED
    diagnosis: str | None = None
    for hypothesis in result.hypotheses:
        if hypothesis.status == "selected":
            diagnosis = hypothesis.statement
            break
    if diagnosis is None:
        for hypothesis in result.hypotheses:
            if hypothesis.status == "supported":
                diagnosis = hypothesis.statement
                break
    successful = list(learning.successful_actions) if learning else []
    selected_action: str | None = successful[-1] if successful else None
    action_result: str | None = None
    if selected_action is not None:
        for action in reversed(result.actions):
            if action.action == selected_action:
                action_result = action.result
                break
    elif result.actions:
        selected_action = result.actions[-1].action
        action_result = result.actions[-1].result
    verification = result.verification
    verification_result: dict[str, object] = {}
    if verification is not None:
        verification_result = {
            "improved": verification.improved,
            "status": verification.status,
            "metrics_before": dict(verification.metrics_before),
            "metrics_after": dict(verification.metrics_after),
        }
    symptoms = list(result.symptoms)[:4]
    symptoms.extend(
        f"{item.signal}={item.value}" for item in result.evidence[:8]
    )
    title = "Payment API experiencing elevated failures"
    if terminal == STATUS_RESOLVED and diagnosis:
        title = diagnosis
    store.mark_stage(record_id, terminal)
    store.update(
        record_id,
        agent_incident_id=result.incident_id,
        title=title,
        status=terminal,
        current_stage=terminal,
        detected_symptoms=symptoms[:12],
        diagnosis=diagnosis,
        selected_action=selected_action,
        action_result=action_result,
        verification_result=verification_result,
        learning_outcome=outcome,
        learning_lesson=learning.lesson if learning else None,
        suitable_for_hindsight=bool(
            learning and learning.suitable_for_hindsight
        ),
        trace={
            "hypotheses": [h.model_dump(mode="json") for h in result.hypotheses],
            "investigation": [
                s.model_dump(mode="json") for s in result.investigation
            ],
            "actions": [a.model_dump(mode="json") for a in result.actions],
            "verification": (
                verification.model_dump(mode="json") if verification else None
            ),
            "learning": learning.model_dump(mode="json") if learning else None,
        },
    )

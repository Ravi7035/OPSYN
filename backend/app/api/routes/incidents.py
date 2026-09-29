"""Incident history endpoints (operator-facing records).

Reads and creates persistent :class:`IncidentRecord` entries. Creating a
record here injects the fault (operator action) but never diagnoses: the
agent still infers everything from observable tool results, and the
stored ``injected_fault_type`` is metadata only — it is never passed to
the reasoning model.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.dependencies import get_incident_store, get_payment_simulator
from app.services.incident_store import IncidentStore
from app.services.payment_simulator import FAULTS, PaymentSimulator, UnknownFaultError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fault_type: str = Field(description="Simulator fault to inject")
    service: str = Field(default="payment-api")
    symptoms: list[str] = Field(default_factory=list)


@router.get("")
async def list_incidents(
    store: IncidentStore = Depends(get_incident_store),
) -> dict[str, object]:
    """All incident records in chronological order."""
    records = store.list_all()
    return {
        "incidents": [r.model_dump(mode="json") for r in records],
        "count": len(records),
    }


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    store: IncidentStore = Depends(get_incident_store),
) -> dict[str, object]:
    """One incident record with its full stored lifecycle and trace."""
    record = store.get(incident_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown incident: {incident_id}",
        )
    return record.model_dump(mode="json")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: IncidentCreateRequest,
    store: IncidentStore = Depends(get_incident_store),
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    """Inject a fault and open its incident record (status INJECTED).

    The fault name is operator metadata for the record. Nothing here
    reaches the agent as a diagnosis.
    """
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
    record = store.create(
        service=payload.service,
        injected_fault_type=payload.fault_type,
        detected_symptoms=list(payload.symptoms),
    )
    logger.info(
        "INCIDENT_OPENED id=%s fault=%s", record.incident_id, payload.fault_type
    )
    return record.model_dump(mode="json")

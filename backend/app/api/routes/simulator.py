"""Payment-api simulator endpoints (agent observation + evaluation harness).

Agent-facing reads (health/metrics/state/logs/snapshot/transactions)
never expose the internal fault name. Fault injection and reset exist
for deterministic evaluation scenarios.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_payment_simulator
from app.services.payment_simulator import (
    PaymentSimulator,
    UnknownActionError,
    UnknownFaultError,
)

router = APIRouter(prefix="/api/simulator", tags=["simulator"])


@router.get("/health")
async def simulator_health(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.get_health()


@router.get("/metrics")
async def simulator_metrics(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.get_metrics()


@router.get("/state")
async def simulator_state(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.get_state()


@router.get("/logs")
async def simulator_logs(
    limit: int = 50,
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.get_logs(limit=limit)


@router.get("/snapshot")
async def simulator_snapshot(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.get_snapshot()


@router.post("/transactions")
async def simulator_transaction(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.process_transaction()


@router.post("/faults/{fault_type}")
async def simulator_inject_fault(
    fault_type: str,
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    try:
        return simulator.inject_fault(fault_type)
    except UnknownFaultError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/actions/{action}")
async def simulator_execute_action(
    action: str,
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    try:
        return simulator.execute_action(action)
    except UnknownActionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/reset")
async def simulator_reset(
    simulator: PaymentSimulator = Depends(get_payment_simulator),
) -> dict[str, object]:
    return simulator.reset()

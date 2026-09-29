"""Hindsight memory endpoints.

Thin API layer: validates input, delegates to HindsightService,
formats responses. Never touches the Hindsight SDK directly.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_hindsight_service
from app.models.incident import RecallQuery
from app.services.hindsight_service import HindsightError, HindsightService

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/test", status_code=status.HTTP_200_OK)
async def memory_test(
    service: HindsightService = Depends(get_hindsight_service),
) -> dict[str, object]:
    """Smoke test: API -> HindsightService -> Hindsight Cloud (retain + recall)."""
    try:
        return await service.retain_and_recall_sample()
    except HindsightError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/recall", status_code=status.HTTP_200_OK)
async def memory_recall(
    payload: RecallQuery,
    service: HindsightService = Depends(get_hindsight_service),
) -> dict[str, object]:
    """Recall relevant historical incidents without retaining anything."""
    try:
        memories = await service.recall_incidents(
            query=payload.query, max_tokens=payload.max_tokens
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HindsightError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return {
        "bank_id": service.bank_id,
        "query": payload.query,
        "recall_count": len(memories),
        "memories": memories,
    }

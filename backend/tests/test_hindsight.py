"""Tests for the Hindsight memory layer.

All tests mock the Hindsight SDK so no credentials or network are needed.
Live Cloud verification is done via POST /memory/test with a real .env.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.incident import Incident
from app.services.hindsight_service import (
    SAMPLE_RECALL_QUERY,
    HindsightNotConfiguredError,
    HindsightService,
)


def _service_with_mock() -> tuple[HindsightService, MagicMock]:
    service = HindsightService(
        api_key="dummy-key",
        base_url="https://api.hindsight.vectorize.io",
        bank_id="test-bank",
    )
    mock_client = MagicMock()
    mock_client.acreate_bank = AsyncMock()
    mock_client.aretain = AsyncMock(return_value=MagicMock(success=True))
    mock_client.arecall = AsyncMock(
        return_value=MagicMock(
            results=[
                MagicMock(
                    text="pool exhaustion root cause",
                    score=0.9,
                    metadata={"incident_id": "INC-2024-001"},
                )
            ]
        )
    )
    service._client = mock_client
    return service, mock_client


def test_missing_api_key_raises() -> None:
    with pytest.raises(HindsightNotConfiguredError):
        HindsightService(api_key="  ", base_url="https://x", bank_id="b")


def test_incident_model_requires_core_fields() -> None:
    incident = Incident(incident_id="INC-1", service="payment-api")
    assert incident.environment == "production"
    assert "INC-1" in incident.to_memory_text()


@pytest.mark.asyncio
async def test_retain_incident_calls_sdk() -> None:
    service, mock_client = _service_with_mock()
    incident = Incident(incident_id="INC-1", service="payment-api")
    result = await service.retain_incident(incident)
    assert result["incident_id"] == "INC-1"
    mock_client.aretain.assert_awaited_once()


@pytest.mark.asyncio
async def test_recall_incidents_returns_memories() -> None:
    service, _ = _service_with_mock()
    memories = await service.recall_incidents(SAMPLE_RECALL_QUERY)
    assert len(memories) == 1
    assert memories[0]["score"] == 0.9


@pytest.mark.asyncio
async def test_recall_rejects_empty_query() -> None:
    service, _ = _service_with_mock()
    with pytest.raises(ValueError):
        await service.recall_incidents("  ")


@pytest.mark.asyncio
async def test_retain_and_recall_sample_flow() -> None:
    service, mock_client = _service_with_mock()
    result = await service.retain_and_recall_sample()
    assert result["bank_id"] == "test-bank"
    assert result["recall_count"] == 1
    mock_client.acreate_bank.assert_awaited_once()
    mock_client.aretain.assert_awaited_once()
    mock_client.arecall.assert_awaited_once()


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

"""Hindsight Cloud memory layer.

This module is the ONLY place that talks to the Hindsight SDK.
API routes and (future) agent code must go through HindsightService,
never import the SDK directly.

No LLM reasoning or incident-response logic lives here — Hindsight
is purely organizational memory: retain experiences, recall them.
"""

import logging
from datetime import datetime, timezone

from hindsight_client import Hindsight

from app.config.settings import Settings
from app.models.incident import Incident

logger = logging.getLogger(__name__)

SAMPLE_INCIDENT = Incident(
    incident_id="INC-2024-001",
    service="payment-api",
    environment="production",
    severity="P2",  # type: ignore[arg-type]
    timestamp=datetime(2024, 5, 14, 10, 30, tzinfo=timezone.utc),
    symptoms=[
        "38% HTTP 5xx on payment-api",
        "p95 latency 8.2 seconds",
        "database connection utilization 100%",
        "payment requests timing out",
    ],
    logs=[
        "ERROR db pool exhausted: timeout waiting for connection",
        "WARN payment request timed out after 8000ms",
    ],
    metrics={
        "http_5xx_rate": "38%",
        "p95_latency_s": "8.2",
        "db_connection_utilization": "100%",
        "http_5xx_rate_after_fix": "0.4%",
    },
    root_cause=(
        "Database connection pool exhaustion caused by increased traffic. "
        "Pool of 50 connections saturated; new payment requests timed out."
    ),
    actions_taken=["Increased DB connection pool from 50 to 150"],
    resolution="5xx reduced from 38% to 0.4%, latency recovered.",
    resolution_time_minutes=42.0,
    customer_impact="Payment requests failing for ~38% of checkout attempts.",
    lesson=(
        "The existing connection pool (50) was insufficient for the "
        "increased traffic; provision headroom and alert on pool saturation."
    ),
)

SAMPLE_RECALL_QUERY = (
    "Find previous production incidents involving payment API "
    "database connection pool exhaustion, high 5xx errors, "
    "high latency, and database connection timeouts. "
    "Return relevant root causes and successful remediation actions."
)


class HindsightError(Exception):
    """Base error for Hindsight failures (credentials/API/network)."""


class HindsightNotConfiguredError(HindsightError):
    """Raised when HINDSIGHT_API_KEY is missing."""


class HindsightService:
    """Thin async wrapper around the Hindsight SDK."""

    def __init__(self, api_key: str, base_url: str, bank_id: str) -> None:
        if not api_key.strip():
            raise HindsightNotConfiguredError(
                "HINDSIGHT_API_KEY is not set. "
                "Configure it in .env (see .env.example)."
            )
        self._bank_id = bank_id
        self._client = Hindsight(base_url=base_url, api_key=api_key)

    @classmethod
    def from_settings(cls, settings: Settings) -> "HindsightService":
        return cls(
            api_key=settings.hindsight_api_key,
            base_url=settings.hindsight_base_url,
            bank_id=settings.hindsight_bank_id,
        )

    @property
    def bank_id(self) -> str:
        return self._bank_id

    async def ensure_bank(self) -> None:
        """Create the memory bank if it does not exist (idempotent)."""
        try:
            await self._client.acreate_bank(
                bank_id=self._bank_id,
                reflect_mission=(
                    "SRE organizational memory: production incidents, "
                    "root causes, and successful remediation actions."
                ),
                background="Memory bank for the SRE AI Incident Response project.",
            )
        except Exception as exc:
            raise HindsightError(
                f"Hindsight ensure_bank failed: {self._safe_message(exc)}"
            ) from exc

    async def retain_incident(self, incident: Incident) -> dict[str, object]:
        """Store one incident experience in the memory bank."""
        try:
            response = await self._client.aretain(
                bank_id=self._bank_id,
                content=incident.to_memory_text(),
                context=incident.to_memory_context(),
                metadata=incident.to_memory_metadata(),
                document_id=incident.incident_id,
                tags=["sre", "incident", incident.service, incident.environment],
            )
        except Exception as exc:
            raise HindsightError(
                f"Hindsight retain failed: {self._safe_message(exc)}"
            ) from exc
        return {
            "incident_id": incident.incident_id,
            "bank_id": self._bank_id,
            "success": bool(getattr(response, "success", True)),
        }

    async def recall_incidents(
        self, query: str, max_tokens: int = 4096
    ) -> list[dict[str, object]]:
        """Retrieve relevant historical incidents for a query."""
        if not query.strip():
            raise ValueError("Recall query must not be empty.")
        try:
            response = await self._client.arecall(
                bank_id=self._bank_id,
                query=query,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise HindsightError(
                f"Hindsight recall failed: {self._safe_message(exc)}"
            ) from exc
        return [self._serialize_result(r) for r in (response.results or [])]

    async def retain_and_recall_sample(self) -> dict[str, object]:
        """End-to-end smoke test: ensure bank, retain sample, recall it."""
        await self.ensure_bank()
        retain_result = await self.retain_incident(SAMPLE_INCIDENT)
        memories = await self.recall_incidents(SAMPLE_RECALL_QUERY)
        for memory in memories:
            logger.info(
                "Recalled memory score=%s text=%s",
                memory.get("score"),
                str(memory.get("text"))[:300],
            )
        return {
            "bank_id": self._bank_id,
            "retain": retain_result,
            "query": SAMPLE_RECALL_QUERY,
            "recall_count": len(memories),
            "memories": memories,
        }

    @staticmethod
    def _serialize_result(result: object) -> dict[str, object]:
        if isinstance(result, dict):
            return {
                "text": result.get("text") or result.get("content"),
                "score": result.get("score"),
                "metadata": result.get("metadata"),
            }
        return {
            "text": getattr(result, "text", None) or str(result),
            "score": getattr(result, "score", None),
            "metadata": getattr(result, "metadata", None),
        }

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        # Never leak credentials: Hindsight SDK errors may echo config.
        message = str(exc)
        for secret_hint in ("Bearer ", "api_key", "API_KEY"):
            if secret_hint in message:
                return f"{type(exc).__name__} (details redacted to protect credentials)"
        return message or type(exc).__name__

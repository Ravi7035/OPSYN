"""Shared FastAPI dependencies.

Exposes the HindsightService as a singleton so every request reuses
one SDK client instead of constructing a new one per request.
"""

from functools import lru_cache

from fastapi import HTTPException, status

from app.config.settings import Settings, get_settings
from app.services.hindsight_service import (
    HindsightNotConfiguredError,
    HindsightService,
)
from app.services.payment_simulator import PaymentSimulator


@lru_cache
def get_hindsight_service() -> HindsightService:
    settings: Settings = get_settings()
    try:
        return HindsightService.from_settings(settings)
    except HindsightNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@lru_cache
def get_payment_simulator() -> PaymentSimulator:
    return PaymentSimulator()


@lru_cache
def get_agent_tools() -> "AgentTools":
    from app.services.agent_tools import AgentTools

    return AgentTools(get_payment_simulator())


@lru_cache
def get_reasoning_model() -> "ReasoningModel":
    """Select the reasoning backend from REASONING_MODEL.

    'deterministic' (default) needs no credentials. 'llm' requires
    GROQ_API_KEY and fails loudly without it — never silently falls back.
    """
    from app.services.reasoning_model import ReasoningModel

    settings: Settings = get_settings()
    choice = (settings.reasoning_model or "deterministic").strip().lower()
    if choice == "deterministic":
        from app.services.reasoning_model import DeterministicReasoningModel

        return DeterministicReasoningModel()
    if choice == "llm":
        from app.services.llm_reasoning_model import (
            LLMNotConfiguredError,
            LLMReasoningModel,
        )

        try:
            return LLMReasoningModel.from_settings(settings)
        except LLMNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unknown REASONING_MODEL: {settings.reasoning_model!r} "
        "(expected 'deterministic' or 'llm').",
    )


@lru_cache
def get_incident_store() -> "IncidentStore":
    """Singleton JSON incident store (MVP persistence, survives restarts)."""
    from app.services.incident_store import IncidentStore

    settings: Settings = get_settings()
    return IncidentStore(settings.incident_store_path)


def get_agent_memory() -> object:
    """Real Hindsight when configured, otherwise a local fallback.

    The agent must run with no API key, so a missing key falls back to
    an in-memory store instead of raising.
    """
    try:
        return get_hindsight_service()
    except Exception:
        from app.services.agent import InMemoryHindsight

        return InMemoryHindsight()


def get_incident_response_agent() -> "IncidentResponseAgent":
    from app.services.agent import (
        MAX_ACTIONS,
        MAX_INVESTIGATION_STEPS,
        IncidentResponseAgent,
    )

    try:
        settings: Settings = get_settings()
        max_steps = settings.agent_max_investigation_steps
        max_actions = settings.agent_max_actions
    except Exception:
        max_steps = MAX_INVESTIGATION_STEPS
        max_actions = MAX_ACTIONS
    return IncidentResponseAgent(
        reasoning_model=get_reasoning_model(),
        tools=get_agent_tools(),
        hindsight=get_agent_memory(),
        max_investigation_steps=max_steps,
        max_actions=max_actions,
    )

"""Focused tests for Point #1: Hindsight central to the learning loop.

Covers the closed loop Incident 1 -> retain -> Incident 2 -> recall ->
reason with memory, with memory treated as fallible evidence:

- Test A (retention): a resolved incident with a failed + successful action
  is retained with the full reasoning trace.
- Test B (recall): Incident 2 retrieves Incident 1's actual experience text.
- Test C (learning): successful and failed actions appear in retained text.
- Test D (influence): relevant memory boosts the matching hypothesis;
  a recalled historical failure is negative evidence.
- Test E (override): a misleading memory does not force the wrong action.
- Test F (audit): no simulator ground truth leaks into retained/recalled text.

Deterministic only: no Groq/network/quota involved.
"""

import pytest

from app.models.incident import Incident, IncidentSource
from app.services.agent import (
    IncidentResponseAgent,
    InMemoryHindsight,
)
from app.services.agent_tools import AgentTools
from app.services.payment_simulator import FAULTS, PaymentSimulator
from app.services.reasoning_model import DeterministicReasoningModel

SECRET_STRINGS = ["active_fault", "expected_action", "root_cause", "fault="] + list(
    FAULTS
)

MISLEADING_DB_MEMORY = """Incident SIM-old: payment-api (production, P2) experienced an issue.
Symptoms: elevated 5xx
Metrics: db_connections=100/100; db_latency_ms=900
Logs: ERROR db pool exhausted
Root cause: unknown
Actions taken: none recorded
Resolution: recovered
Lesson: DB pool exhaustion indicated by saturated connections.
OBSERVED EVIDENCE:
- db_connections: 100/100 (provenance=observed)
HYPOTHESES:
- [supported] DB pool exhaustion (confidence=0.9)
INVESTIGATION:
- step-1 | tool=get_metrics | started_at=2026-01-01T00:00:00+00:00 | result=5xx=25
ACTIONS:
- action-1 | clear_db_connections | target=payment-api | status=executed | result=5xx 25->0.2 | resolved
VERIFICATION: status=resolved, improved=True
- before: http_5xx_rate=25.0
- after: http_5xx_rate=0.2
LEARNING: outcome=resolved, suitable_for_hindsight=True
- successful: clear_db_connections
- lesson: saturated DB connections indicated DB pool exhaustion; clear_db_connections restored health."""


def _incident(incident_id: str) -> Incident:
    return Incident(
        incident_id=incident_id,
        service="payment-api",
        environment="production",
        source=IncidentSource.SIMULATOR,
        symptoms=["test investigation"],
    )


def _agent(
    simulator: PaymentSimulator,
    hindsight: InMemoryHindsight,
    reasoning: object | None = None,
) -> IncidentResponseAgent:
    return IncidentResponseAgent(
        reasoning_model=reasoning or DeterministicReasoningModel(),  # type: ignore[arg-type]
        tools=AgentTools(simulator),
        hindsight=hindsight,
    )


async def _recall_texts(memory: InMemoryHindsight, query: str) -> list[str]:
    return [str(m.get("text") or "") for m in await memory.recall_incidents(query)]


# -- Test A + C: retention contains the full reasoning trace --------------------


@pytest.mark.asyncio
async def test_retained_memory_contains_full_reasoning_trace() -> None:
    memory = InMemoryHindsight()
    simulator = PaymentSimulator()
    simulator.inject_fault("db_pool_exhaustion")
    agent = _agent(
        simulator,
        memory,
        DeterministicReasoningModel(force_first_action="restart_redis"),
    )
    result = await agent.run(_incident("SIM-loop-1"))

    assert result.learning is not None
    assert result.learning.outcome == "resolved"
    assert "restart_redis" in result.learning.failed_actions
    assert "clear_db_connections" in result.learning.successful_actions
    assert memory.retained_count == 1

    texts = await _recall_texts(memory, "db pool connections saturated 5xx")
    assert len(texts) == 1
    text = texts[0]
    # Test A: every reasoning stage is present in the retained experience.
    for section in (
        "OBSERVED EVIDENCE:",
        "HYPOTHESES:",
        "INVESTIGATION:",
        "ACTIONS:",
        "VERIFICATION:",
        "LEARNING:",
    ):
        assert section in text, section
    # Test C: both the failure and the success are preserved as learning.
    assert "restart_redis" in text
    assert "clear_db_connections" in text
    assert "- failed: restart_redis" in text
    assert "- successful: clear_db_connections" in text
    assert "Failed actions with no improvement: restart_redis" in text


# -- Test B: Incident 2 recalls Incident 1's actual experience ------------------


@pytest.mark.asyncio
async def test_incident2_recalls_incident1_experience() -> None:
    memory = InMemoryHindsight()

    first_sim = PaymentSimulator()
    first_sim.inject_fault("db_pool_exhaustion")
    first = await _agent(first_sim, memory).run(_incident("SIM-loop-1"))
    assert first.learning is not None and first.learning.outcome == "resolved"

    second_sim = PaymentSimulator()
    second_sim.inject_fault("db_pool_exhaustion")
    agent2 = _agent(second_sim, memory)

    # Prove recall itself returns Incident 1's experience text, not a boolean.
    recalled = await memory.recall_incidents(
        agent2._recall_query(_incident("SIM-loop-2"), second_sim.get_metrics())
    )
    recalled_ids = [
        m.get("metadata", {}).get("incident_id")
        for m in recalled
        if isinstance(m.get("metadata"), dict)
    ]
    assert "SIM-loop-1" in recalled_ids
    recalled_text = " ".join(str(m.get("text") or "") for m in recalled)
    assert "clear_db_connections" in recalled_text
    # The actual lesson travelled with the memory, not just an action name.
    assert "restored service health" in recalled_text
    assert "LEARNING:" in recalled_text

    second = await agent2.run(_incident("SIM-loop-2"))
    assert second.learning is not None
    assert second.learning.outcome == "resolved"
    assert "clear_db_connections" in second.learning.successful_actions


# -- Test D: memory influences hypothesis scoring --------------------------------


def _db_observations() -> dict:
    return {
        "metrics": {
            "db_connections": 96,
            "db_connection_limit": 100,
            "db_latency_ms": 600,
            "http_5xx_rate": 12.0,
            "cpu": 50.0,
            "memory": 51.0,
            "redis_health": "healthy",
            "dependency_latency_ms": 40,
            "request_rate": 120,
            "queue_depth": 6,
            "disk_utilization": 42,
            "deployment_version": "1.4.2",
            "deployment_status": "healthy",
            "p95_latency_ms": 1800,
        },
        "state": {
            "status": "degraded",
            "deployment": {"version": "1.4.2", "status": "healthy"},
            "redis": {"status": "healthy"},
            "disk": {"utilization_percent": 42, "status": "ok"},
        },
        "health": {"status": "degraded"},
        "logs": {"logs": ["ERROR payment request failed: database timeout"]},
    }


def test_relevant_memory_boosts_matching_hypothesis() -> None:
    model = DeterministicReasoningModel()
    observations = _db_observations()

    without = {h.statement: h for h in model.evaluate_hypotheses(observations, [])}
    with_memory = {
        h.statement: h
        for h in model.evaluate_hypotheses(
            observations,
            [
                {
                    "text": "DB pool exhaustion with saturated connection pool; "
                    "clear_db_connections restored health.",
                    "score": 0.9,
                    "metadata": {"incident_id": "SIM-old"},
                }
            ],
        )
    }
    db_without = without["DB pool exhaustion"]
    db_with = with_memory["DB pool exhaustion"]
    assert (db_with.confidence or 0) > (db_without.confidence or 0)
    assert any("hindsight" in s.lower() for s in db_with.supporting)


def test_historical_failure_is_negative_evidence() -> None:
    model = DeterministicReasoningModel()
    observations = _db_observations()
    success_memory = {
        "text": "DB pool exhaustion with saturated connection pool; "
        "clear_db_connections restored health (5xx < 1%).",
        "score": 0.9,
        "metadata": {"incident_id": "SIM-good"},
    }
    failure_memory = {
        "text": "Suspected DB pool exhaustion but clear_db_connections failed "
        "with no significant change; cause was elsewhere.",
        "score": 0.9,
        "metadata": {"incident_id": "SIM-bad"},
    }
    success = {
        h.statement: h
        for h in model.evaluate_hypotheses(observations, [success_memory])
    }["DB pool exhaustion"]
    failure = {
        h.statement: h
        for h in model.evaluate_hypotheses(observations, [failure_memory])
    }["DB pool exhaustion"]

    assert (failure.confidence or 0) < (success.confidence or 0)
    assert any("failing before" in c for c in failure.contradicting)
    # Current evidence stays authoritative: strong DB signals still support.
    assert failure.status == "supported"


# -- Test E: misleading memory rejected end to end -------------------------------


@pytest.mark.asyncio
async def test_misleading_memory_does_not_force_wrong_action() -> None:
    memory = InMemoryHindsight()
    misleading = _incident("SIM-old-db")
    await memory.retain_incident(misleading)
    # Overwrite the retained text with a controlled misleading experience:
    # a DB-pool success story that must NOT dictate the next diagnosis.
    memory._store[0]["text"] = MISLEADING_DB_MEMORY  # type: ignore[index]

    simulator = PaymentSimulator()
    simulator.inject_fault("bad_deployment")
    agent = _agent(simulator, memory)
    result = await agent.run(_incident("SIM-loop-misled"))

    assert result.learning is not None
    assert result.learning.outcome == "resolved"
    assert "rollback_deployment" in result.learning.successful_actions
    assert "clear_db_connections" not in result.learning.successful_actions
    by_statement = {h.statement: h for h in result.hypotheses}
    assert by_statement["DB pool exhaustion"].status == "rejected"
    assert by_statement["bad deployment"].status in ("supported", "selected")


# -- Test F: hidden-state audit for retained and recalled memories ----------------


@pytest.mark.asyncio
async def test_no_ground_truth_in_retained_or_recalled_memories() -> None:
    # Neutral incident IDs: the evaluator must never smuggle the scenario
    # label into the incident (see new_scenario_incident's eval-{mode}-{seq}).
    for seq, fault in enumerate(("db_pool_exhaustion", "bad_deployment")):
        memory = InMemoryHindsight()
        simulator = PaymentSimulator()
        simulator.inject_fault(fault)
        result = await _agent(simulator, memory).run(_incident(f"SIM-audit-{seq:02d}"))
        assert result.learning is not None

        texts = await _recall_texts(memory, "sre incident payment-api")
        assert texts, "retained incident must be recallable"
        for text in texts:
            for secret in SECRET_STRINGS:
                assert secret not in text, f"{secret!r} leaked for {fault}"

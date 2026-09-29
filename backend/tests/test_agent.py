"""Tests for the OPSYN agent core + tool layer (no LLM required).

The tests control the environment (fault injection) but never expose
hidden simulator state to the agent: all agent input flows through
AgentTools, which is verified to strip secrets.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.models.incident import Hypothesis, Incident, IncidentSource
from app.services.agent import (
    MAX_ACTIONS,
    MAX_INVESTIGATION_STEPS,
    IncidentResponseAgent,
    InMemoryHindsight,
)
from app.services.agent_tools import ACTION_TOOLS, AgentTools
from app.services.payment_simulator import FAULTS, PaymentSimulator
from app.services.reasoning_model import (
    AgentState,
    DeterministicReasoningModel,
    ReasoningDecision,
)

SECRET_STRINGS = [
    "active_fault",
    "expected_action",
    "root_cause",
    "db_pool_exhaustion",
    "bad_deployment",
    "memory_leak",
    "redis_failure",
    "dependency_timeout",
    "traffic_spike",
    "cache_stampede",
    "disk_exhaustion",
]

RECOVERY = {
    "db_pool_exhaustion": "clear_db_connections",
    "bad_deployment": "rollback_deployment",
    "memory_leak": "restart_service",
    "redis_failure": "restart_redis",
    "dependency_timeout": "restore_dependency",
    "traffic_spike": "scale_service",
    "cache_stampede": "restart_service",
    "disk_exhaustion": "free_disk",
}


class MockHindsight:
    """Tracks retain/recall without network or credentials."""

    def __init__(self, memories: list[dict] | None = None) -> None:
        self._memories = memories or []
        self.retained: list[Incident] = []
        self.recall_queries: list[str] = []

    async def retain_incident(self, incident: Incident) -> dict[str, object]:
        self.retained.append(incident)
        return {"incident_id": incident.incident_id, "success": True}

    async def recall_incidents(
        self, query: str, max_tokens: int = 4096
    ) -> list[dict[str, object]]:
        self.recall_queries.append(query)
        return list(self._memories)


class FakeNeverActsModel:
    """Reasoner that investigates forever: forces the escalation path."""

    def evaluate_hypotheses(
        self, observations, memories, observation_history=None, failed_actions=None
    ) -> list[Hypothesis]:
        return [
            Hypothesis(
                statement="unclear cause",
                status="considered",
                confidence=0.2,
                supporting=[],
                contradicting=["insufficient evidence"],
            )
        ]

    def choose_next_step(self, state: AgentState) -> ReasoningDecision:
        if "get_snapshot" not in state.tools_used:
            return ReasoningDecision(
                type="investigate", tool="get_snapshot", reasoning="fake: digging"
            )
        return ReasoningDecision(
            type="investigate", tool="get_metrics", reasoning="fake: still digging"
        )


def _fresh_agent(
    simulator: PaymentSimulator,
    hindsight: object | None = None,
    reasoning: object | None = None,
    max_steps: int = MAX_INVESTIGATION_STEPS,
    max_actions: int = MAX_ACTIONS,
) -> IncidentResponseAgent:
    return IncidentResponseAgent(
        reasoning_model=reasoning or DeterministicReasoningModel(),  # type: ignore[arg-type]
        tools=AgentTools(simulator),
        hindsight=hindsight if hindsight is not None else MockHindsight(),
        max_investigation_steps=max_steps,
        max_actions=max_actions,
    )


def _incident(incident_id: str = "SIM-test") -> Incident:
    return Incident(
        incident_id=incident_id,
        service="payment-api",
        environment="production",
        source=IncidentSource.SIMULATOR,
        symptoms=["test investigation"],
    )


# -- Test 1: baseline observation -------------------------------------------


@pytest.mark.asyncio
async def test_baseline_observation_healthy() -> None:
    simulator = PaymentSimulator()
    agent = _fresh_agent(simulator)
    result = await agent.run(_incident("SIM-healthy"))

    assert len(result.investigation) >= 4  # health, metrics, state, logs
    assert len(result.evidence) > 0
    tools_used = {step.tool for step in result.investigation}
    assert {"get_health", "get_metrics", "get_state", "get_logs"} <= tools_used
    assert result.learning is not None
    # Healthy system: no remediation actions should be taken.
    assert result.actions == []


# -- Tests 2+3 (+10): each fault resolves ------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("fault,action", sorted(RECOVERY.items()))
async def test_each_fault_resolves(fault: str, action: str) -> None:
    simulator = PaymentSimulator()
    simulator.inject_fault(fault)
    memory = MockHindsight()
    agent = _fresh_agent(simulator, hindsight=memory)
    result = await agent.run(_incident(f"SIM-{fault}"))

    assert result.learning is not None
    assert result.learning.outcome == "resolved", (
        f"{fault}: hypotheses={[ (h.statement, h.status, h.confidence) for h in result.hypotheses ]}"
    )
    assert action in result.learning.successful_actions
    assert result.verification is not None
    assert result.verification.improved is True
    assert result.verification.status == "resolved"
    assert result.verification.metrics_after.get("http_5xx_rate", 99) < 1.0
    # Retention happened.
    assert len(memory.retained) == 1


# -- Test 4: wrong action recovery --------------------------------------------


@pytest.mark.asyncio
async def test_wrong_action_then_recovery() -> None:
    simulator = PaymentSimulator()
    simulator.inject_fault("db_pool_exhaustion")
    memory = MockHindsight()
    reasoning = DeterministicReasoningModel(force_first_action="restart_redis")
    agent = _fresh_agent(simulator, hindsight=memory, reasoning=reasoning)
    result = await agent.run(_incident("SIM-wrong-action"))

    assert result.learning is not None
    assert result.learning.outcome == "resolved"
    assert "restart_redis" in result.learning.failed_actions
    assert "clear_db_connections" in result.learning.successful_actions
    # Both attempts are recorded on the incident.
    attempted = [a.action for a in result.actions]
    assert attempted[0] == "restart_redis"
    assert "clear_db_connections" in attempted
    # The failed action is not blindly retried.
    assert attempted.count("restart_redis") == 1


# -- Test 5: hypothesis rejection ----------------------------------------------


def test_hypothesis_rejection_despite_memory() -> None:
    observations = {
        "metrics": {
            "db_connections": 42,
            "db_connection_limit": 100,
            "db_latency_ms": 22,
            "http_5xx_rate": 30.0,
            "cpu": 50.0,
            "memory": 51.0,
            "redis_health": "healthy",
            "dependency_latency_ms": 40,
            "request_rate": 120,
            "queue_depth": 6,
            "disk_utilization": 42,
            "deployment_version": "1.5.0",
            "deployment_status": "just_deployed",
            "p95_latency_ms": 1800,
        },
        "state": {
            "status": "degraded",
            "deployment": {"version": "1.5.0", "status": "just_deployed"},
            "redis": {"status": "healthy"},
            "disk": {"utilization_percent": 42, "status": "ok"},
        },
        "health": {"status": "degraded"},
        "logs": {"logs": ["ERROR transaction request returned 500"]},
    }
    memories = [
        {
            "text": "DB pool exhaustion with 100/100 connections; "
            "clear_db_connections restored health.",
            "score": 0.95,
            "metadata": {"incident_id": "SIM-old"},
        }
    ]
    model = DeterministicReasoningModel()
    hypotheses = model.evaluate_hypotheses(observations, memories)

    by_statement = {h.statement: h for h in hypotheses}
    db_hypothesis = by_statement["DB pool exhaustion"]
    deploy_hypothesis = by_statement["bad deployment"]
    assert db_hypothesis.status == "rejected", (
        f"DB hypothesis must be rejected on healthy DB evidence: {db_hypothesis}"
    )
    assert deploy_hypothesis.status == "supported"
    assert (deploy_hypothesis.confidence or 0) > (db_hypothesis.confidence or 0)


# -- Test 6: hindsight retention -------------------------------------------------


@pytest.mark.asyncio
async def test_hindsight_retention_called() -> None:
    simulator = PaymentSimulator()
    simulator.inject_fault("bad_deployment")
    memory = MockHindsight()
    agent = _fresh_agent(simulator, hindsight=memory)
    result = await agent.run(_incident("SIM-retain"))

    assert result.learning is not None
    assert result.learning.suitable_for_hindsight is True
    assert len(memory.retained) == 1
    retained = memory.retained[0]
    assert "rollback_deployment" in retained.to_memory_text()
    assert retained.to_memory_context() != ""
    assert retained.to_memory_metadata()["incident_id"] == "SIM-retain"


# -- Test 7: failed investigation --------------------------------------------------


@pytest.mark.asyncio
async def test_failed_investigation_escalates_and_learns() -> None:
    simulator = PaymentSimulator()
    simulator.inject_fault("db_pool_exhaustion")
    memory = MockHindsight()
    agent = _fresh_agent(
        simulator,
        hindsight=memory,
        reasoning=FakeNeverActsModel(),  # type: ignore[arg-type]
        max_steps=6,
        max_actions=1,
    )
    result = await agent.run(_incident("SIM-failed"))

    assert result.learning is not None
    assert result.learning.outcome in ("unresolved", "escalated")
    assert result.actions == []
    assert len(memory.retained) == 1  # even failures are retained
    assert len(result.investigation) <= 6


# -- Test 8: hidden-state protection -----------------------------------------------


@pytest.mark.asyncio
async def test_hidden_state_never_reaches_agent() -> None:
    for index, fault in enumerate(FAULTS):
        simulator = PaymentSimulator()
        simulator.inject_fault(fault)
        tools = AgentTools(simulator)
        tool_payloads: list[object] = []
        for tool_name in (
            "get_health",
            "get_metrics",
            "get_state",
            "get_logs",
            "get_snapshot",
        ):
            tool_payloads.append((await tools.run_tool(tool_name)).model_dump(mode="json"))
        for action in ACTION_TOOLS:
            tool_payloads.append(
                (await tools.run_tool(action)).model_dump(mode="json")
            )
        # Tool responses must not even carry hidden-state KEYS.
        tool_blob = json.dumps(tool_payloads, default=str)
        for secret in ("active_fault", "expected_action", "root_cause"):
            assert secret not in tool_blob, f"{secret!r} leaked during {fault}"

        agent = _fresh_agent(simulator)
        result = await agent.run(_incident(f"SIM-hide-{index:02d}"))
        # The incident carries schema field names (root_cause=None), but must
        # never contain hidden VALUES: no fault identity, no expected action.
        assert result.root_cause is None
        assert result.fault_type is None
        incident_blob = json.dumps(result.model_dump(mode="json"), default=str)
        for secret in list(FAULTS) + ["active_fault", "expected_action"]:
            assert secret not in incident_blob, f"{secret!r} leaked during {fault}"


# -- Test 9: loop bounds -------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_bounds() -> None:
    for fault in ("db_pool_exhaustion", "bad_deployment", "traffic_spike"):
        simulator = PaymentSimulator()
        simulator.inject_fault(fault)
        agent = _fresh_agent(simulator)
        result = await agent.run(_incident(f"SIM-bounds-{fault}"))
        assert len(result.investigation) <= MAX_INVESTIGATION_STEPS
        assert len(result.actions) <= MAX_ACTIONS


# -- Test 11 (§21): learning across incidents ------------------------------------------


@pytest.mark.asyncio
async def test_learning_db_then_deployment_overrides_memory() -> None:
    memory = InMemoryHindsight()

    first_sim = PaymentSimulator()
    first_sim.inject_fault("db_pool_exhaustion")
    first_agent = _fresh_agent(first_sim, hindsight=memory)
    first = await first_agent.run(_incident("SIM-learn-1"))
    assert first.learning is not None and first.learning.outcome == "resolved"
    assert memory.retained_count == 1

    second_sim = PaymentSimulator()
    second_sim.inject_fault("bad_deployment")
    second_agent = _fresh_agent(second_sim, hindsight=memory)
    second = await second_agent.run(_incident("SIM-learn-2"))

    assert second.learning is not None
    assert second.learning.outcome == "resolved"
    assert "rollback_deployment" in second.learning.successful_actions
    by_statement = {h.statement: h for h in second.hypotheses}
    assert by_statement["DB pool exhaustion"].status == "rejected"
    assert by_statement["bad deployment"].status in ("supported", "selected")


# -- Agent API endpoint ---------------------------------------------------------------


def test_agent_endpoint_runs_and_hides_state() -> None:
    from app.core import dependencies as deps
    from app.main import app

    simulator = PaymentSimulator()
    memory = MockHindsight()
    test_agent = _fresh_agent(simulator, hindsight=memory)
    app.dependency_overrides[deps.get_incident_response_agent] = lambda: test_agent
    app.dependency_overrides[deps.get_payment_simulator] = lambda: simulator
    try:
        client = TestClient(app)
        response = client.post(
            "/api/agent/run",
            json={"incident_id": "SIM-api-1", "fault_type": "redis_failure"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["incident_id"] == "SIM-api-1"
        assert body["outcome"] == "resolved"
        assert any(
            h["statement"] == "redis failure" for h in body["hypotheses"]
        )
        assert len(body["investigation"]) >= 4
        assert len(body["actions"]) >= 1
        assert body["verification"]["improved"] is True
        assert body["learning"]["suitable_for_hindsight"] is True
        # Tool-shaped sections carry no hidden keys; the incident envelope
        # carries schema field names but no hidden values.
        tool_blob = json.dumps(
            {
                "hypotheses": body["hypotheses"],
                "investigation": body["investigation"],
                "actions": body["actions"],
                "verification": body["verification"],
                "learning": body["learning"],
            }
        )
        for secret in ("active_fault", "expected_action", "root_cause"):
            assert secret not in tool_blob, f"{secret!r} leaked via API"
        assert body["incident"]["root_cause"] is None
        assert body["incident"]["fault_type"] is None
        incident_blob = json.dumps(body["incident"])
        for secret in list(FAULTS) + ["active_fault", "expected_action"]:
            assert secret not in incident_blob, f"{secret!r} leaked via API"
    finally:
        app.dependency_overrides.clear()

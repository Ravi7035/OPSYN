"""Tests for persistent incident records (no static data, no LLM needed).

Every test isolates its store in a tmp directory via dependency override,
so the real ``backend/data/incidents.json`` is never touched here.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import dependencies as deps
from app.main import app
from app.models.incident_records import IncidentRecord
from app.services.agent import InMemoryHindsight, IncidentResponseAgent
from app.services.agent_tools import AgentTools
from app.services.incident_store import IncidentStore
from app.services.payment_simulator import FAULTS, PaymentSimulator
from app.services.reasoning_model import DeterministicReasoningModel


@pytest.fixture()
def tmp_store(tmp_path):
    return IncidentStore(tmp_path / "incidents.json")


@pytest.fixture()
def client(tmp_store):
    simulator = PaymentSimulator()
    memory = InMemoryHindsight()
    agent = IncidentResponseAgent(
        reasoning_model=DeterministicReasoningModel(),
        tools=AgentTools(simulator),
        hindsight=memory,
    )
    app.dependency_overrides[deps.get_incident_response_agent] = lambda: agent
    app.dependency_overrides[deps.get_payment_simulator] = lambda: simulator
    # Routes bind get_incident_store at import; override the dependency.
    app.dependency_overrides[deps.get_incident_store] = lambda: tmp_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_empty_store_lists_zero_incidents(client):
    response = client.get("/api/incidents")
    assert response.status_code == 200
    assert response.json() == {"incidents": [], "count": 0}


def test_unknown_incident_returns_404(client):
    assert client.get("/api/incidents/INC-2026-999").status_code == 404


def test_unknown_fault_creates_no_record(client, tmp_store):
    response = client.post("/api/incidents", json={"fault_type": "nope"})
    assert response.status_code == 404
    assert tmp_store.list_all() == []


def test_full_lifecycle_db_pool_exhaustion(client, tmp_store):
    created = client.post(
        "/api/incidents", json={"fault_type": "db_pool_exhaustion"}
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["incident_id"]
    assert record_id.startswith("INC-")
    assert created.json()["status"] == "INJECTED"
    assert created.json()["injected_fault_type"] == "db_pool_exhaustion"

    run = client.post("/api/agent/run", json={"incident_record_id": record_id})
    assert run.status_code == 200, run.text
    assert run.json()["incident_record_id"] == record_id
    assert run.json()["outcome"] == "resolved"

    stored = client.get(f"/api/incidents/{record_id}").json()
    assert stored["status"] == "RESOLVED"
    assert stored["resolved_at"] is not None
    assert stored["diagnosis"] == "DB pool exhaustion"
    assert stored["selected_action"] == "clear_db_connections"
    assert stored["verification_result"]["improved"] is True
    assert stored["recalled_memory_count"] >= 0
    assert stored["learning_outcome"] == "resolved"
    assert stored["suitable_for_hindsight"] is True
    stages = [s["stage"] for s in stored["stage_history"]]
    for expected in (
        "INJECTED",
        "INVESTIGATING",
        "REMEDIATING",
        "VERIFYING",
        "RESOLVED",
    ):
        assert expected in stages, stages
    assert stored["trace"]["hypotheses"], "full trace must be retained"
    assert stored["trace"]["actions"], "full trace must be retained"

    # The agent-facing trace stayed clean: fault is record metadata only.
    trace_blob = json.dumps(stored["trace"])
    for secret in list(FAULTS) + ["active_fault", "expected_action"]:
        assert secret not in trace_blob, secret


def test_agent_incident_has_no_fault_knowledge(client):
    run = client.post(
        "/api/agent/run", json={"fault_type": "bad_deployment"}
    ).json()
    assert run["incident"]["fault_type"] is None
    assert run["incident"]["root_cause"] is None
    incident_blob = json.dumps(run["incident"])
    for secret in list(FAULTS) + ["active_fault", "expected_action"]:
        assert secret not in incident_blob, secret
    # ...while the operator record legitimately names the injected fault.
    record = client.get(f"/api/incidents/{run['incident_record_id']}").json()
    assert record["injected_fault_type"] == "bad_deployment"
    assert record["status"] == "RESOLVED"


def test_two_incidents_appear_in_chronological_order(client):
    first = client.post(
        "/api/incidents", json={"fault_type": "db_pool_exhaustion"}
    ).json()
    client.post("/api/agent/run", json={"incident_record_id": first["incident_id"]})
    second = client.post(
        "/api/incidents", json={"fault_type": "disk_exhaustion"}
    ).json()
    client.post("/api/agent/run", json={"incident_record_id": second["incident_id"]})

    body = client.get("/api/incidents").json()
    assert body["count"] == 2
    assert [r["incident_id"] for r in body["incidents"]] == [
        first["incident_id"],
        second["incident_id"],
    ]
    assert all(r["status"] == "RESOLVED" for r in body["incidents"])
    assert body["incidents"][1]["injected_fault_type"] == "disk_exhaustion"
    assert body["incidents"][1]["selected_action"] == "free_disk"


def test_records_survive_store_reload(tmp_path):
    path = tmp_path / "incidents.json"
    first = IncidentStore(path)
    created = first.create(injected_fault_type="traffic_spike")
    second = IncidentStore(path)
    reloaded = second.get(created.incident_id)
    assert reloaded is not None
    assert reloaded.injected_fault_type == "traffic_spike"
    assert [r.incident_id for r in second.list_all()] == [created.incident_id]
    assert isinstance(reloaded, IncidentRecord)


def test_legacy_run_without_record_id_still_creates_record(client):
    run = client.post("/api/agent/run", json={"fault_type": "redis_failure"})
    assert run.status_code == 200
    record_id = run.json()["incident_record_id"]
    stored = client.get(f"/api/incidents/{record_id}").json()
    assert stored["status"] == "RESOLVED"
    assert stored["selected_action"] == "restart_redis"

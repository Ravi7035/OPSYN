"""Tests for the payment-api simulator (deterministic environment)."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.payment_simulator import ACTIONS, FAULTS

client = TestClient(app)

BASE = "/api/simulator"

SECRET_STRINGS = list(FAULTS) + ["active_fault", "root_cause", "expected_action"]

RECOVERY = {
    "db_pool_exhaustion": "clear_db_connections",
    "bad_deployment": "rollback_deployment",
    "memory_leak": "restart_service",
    "redis_failure": "restart_redis",
    "dependency_timeout": "restore_dependency",
    "traffic_spike": "scale_service",
    "disk_exhaustion": "free_disk",
}


@pytest.fixture(autouse=True)
def _reset():
    response = client.post(f"{BASE}/reset")
    assert response.status_code == 200
    yield response


def _metrics() -> dict:
    response = client.get(f"{BASE}/metrics")
    assert response.status_code == 200
    return response.json()


def test_healthy_baseline() -> None:
    health = client.get(f"{BASE}/health").json()
    assert health == {
        "service": "payment-api",
        "environment": "production",
        "status": "healthy",
    }
    metrics = _metrics()
    assert metrics["cpu"] == pytest.approx(35.2)
    assert metrics["memory"] == pytest.approx(47.8)
    assert metrics["db_connections"] == 20
    assert metrics["db_connection_limit"] == 100
    assert metrics["redis_health"] == "healthy"
    assert metrics["http_5xx_rate"] < 1.0
    assert 100 <= metrics["p95_latency_ms"] <= 150
    assert 200 <= metrics["p99_latency_ms"] <= 300
    assert metrics["deployment_status"] == "healthy"


def test_db_pool_exhaustion_signature() -> None:
    client.post(f"{BASE}/faults/db_pool_exhaustion")
    metrics = _metrics()
    assert metrics["db_connections"] == 100
    assert metrics["db_latency_ms"] >= 800
    assert metrics["http_5xx_rate"] >= 20
    assert metrics["p95_latency_ms"] >= 2000
    assert metrics["cpu"] < 60  # connection-bound, not CPU-bound
    assert client.get(f"{BASE}/health").json()["status"] == "degraded"


def test_bad_deployment_signature() -> None:
    client.post(f"{BASE}/faults/bad_deployment")
    metrics = _metrics()
    state = client.get(f"{BASE}/state").json()
    assert metrics["http_5xx_rate"] >= 10
    assert metrics["p95_latency_ms"] >= 1500
    assert state["deployment"]["version"] == "1.5.0"
    assert state["deployment"]["status"] == "just_deployed"
    assert "bad" not in state["deployment"]["status"]


def test_memory_leak_signature() -> None:
    client.post(f"{BASE}/faults/memory_leak")
    client.get(f"{BASE}/metrics")
    metrics = _metrics()
    assert metrics["memory"] > 85
    assert metrics["p95_latency_ms"] > 300


def test_redis_failure_signature() -> None:
    client.post(f"{BASE}/faults/redis_failure")
    metrics = _metrics()
    state = client.get(f"{BASE}/state").json()
    assert state["redis"]["status"] == "unavailable"
    assert metrics["http_5xx_rate"] >= 10
    assert metrics["p95_latency_ms"] >= 1000


def test_dependency_timeout_signature() -> None:
    client.post(f"{BASE}/faults/dependency_timeout")
    metrics = _metrics()
    assert metrics["dependency_latency_ms"] >= 4000
    assert metrics["p95_latency_ms"] >= 4000
    assert metrics["http_5xx_rate"] >= 15


def test_traffic_spike_signature() -> None:
    client.post(f"{BASE}/faults/traffic_spike")
    metrics = _metrics()
    assert metrics["request_rate"] >= 1000
    assert metrics["cpu"] >= 85
    assert metrics["queue_depth"] >= 400


def test_cache_stampede_signature() -> None:
    client.post(f"{BASE}/faults/cache_stampede")
    metrics = _metrics()
    assert metrics["db_connections"] >= 90
    assert metrics["db_latency_ms"] >= 500
    assert metrics["cpu"] >= 75


def test_disk_exhaustion_signature() -> None:
    client.post(f"{BASE}/faults/disk_exhaustion")
    metrics = _metrics()
    state = client.get(f"{BASE}/state").json()
    assert metrics["disk_utilization"] >= 95
    assert state["disk"]["status"] == "full"
    assert metrics["http_5xx_rate"] >= 5


def test_unknown_fault_rejected() -> None:
    response = client.post(f"{BASE}/faults/not_a_fault")
    assert response.status_code == 404


def test_agent_responses_hide_root_cause() -> None:
    for fault in FAULTS:
        client.post(f"{BASE}/reset")
        client.post(f"{BASE}/faults/{fault}")
        payloads = [
            client.get(f"{BASE}/health").json(),
            client.get(f"{BASE}/metrics").json(),
            client.get(f"{BASE}/state").json(),
            client.get(f"{BASE}/logs").json(),
            client.get(f"{BASE}/snapshot").json(),
            client.post(f"{BASE}/transactions").json(),
        ]
        for action in ACTIONS:
            payloads.append(client.post(f"{BASE}/actions/{action}").json())
        blob = json.dumps(payloads)
        for secret in SECRET_STRINGS:
            assert secret not in blob, f"{secret!r} leaked during {fault}"


def test_recovery_for_each_fault() -> None:
    for fault, action in RECOVERY.items():
        client.post(f"{BASE}/reset")
        client.post(f"{BASE}/faults/{fault}")
        before = _metrics()
        assert before["http_5xx_rate"] >= 2
        result = client.post(f"{BASE}/actions/{action}").json()
        assert result["status"] == "executed"
        after = _metrics()
        assert after["http_5xx_rate"] < 1.0
        assert after["db_connections"] == 20
        assert client.get(f"{BASE}/health").json()["status"] == "healthy"


def test_incorrect_action_does_not_resolve() -> None:
    client.post(f"{BASE}/faults/db_pool_exhaustion")
    result = client.post(f"{BASE}/actions/restart_redis").json()
    assert result["status"] == "executed"
    metrics = _metrics()
    assert metrics["db_connections"] == 100
    assert metrics["http_5xx_rate"] >= 20
    assert client.get(f"{BASE}/health").json()["status"] == "degraded"


def test_unknown_action_rejected() -> None:
    response = client.post(f"{BASE}/actions/reboot_everything")
    assert response.status_code == 404


def test_reset_restores_baseline() -> None:
    client.post(f"{BASE}/faults/traffic_spike")
    client.post(f"{BASE}/actions/scale_service")
    client.post(f"{BASE}/reset")
    assert client.get(f"{BASE}/health").json()["status"] == "healthy"
    metrics = _metrics()
    assert metrics["cpu"] == pytest.approx(35.2)
    assert metrics["db_connections"] == 20
    assert metrics["deployment_version"] == "1.4.2"
    assert metrics["disk_utilization"] == 42
    assert metrics["redis_health"] == "healthy"


def test_transactions_healthy_vs_faulted() -> None:
    healthy = [client.post(f"{BASE}/transactions").json() for _ in range(10)]
    assert all(t["status"] == "success" and t["status_code"] == 200 for t in healthy)
    client.post(f"{BASE}/faults/db_pool_exhaustion")
    faulted = [client.post(f"{BASE}/transactions").json() for _ in range(10)]
    assert any(t["status"] == "failed" for t in faulted)


def test_repeat_sequence_is_deterministic() -> None:
    def _sequence() -> dict:
        client.post(f"{BASE}/reset")
        client.post(f"{BASE}/faults/dependency_timeout")
        return _metrics()

    first, second = _sequence(), _sequence()
    assert first == second

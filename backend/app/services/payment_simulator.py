"""In-memory payment-api simulator.

Deterministic environment for the future OPSYN agent: exposes observable
symptoms (metrics/logs/state/transactions), accepts fault injection and
controlled remediation actions. Contains no agent, LLM, or diagnostic
logic — the agent must infer causes from symptoms.

`active_fault` is internal evaluation state and is never included in
agent-facing responses.
"""

from datetime import datetime, timedelta, timezone

BASE_TIME = datetime(2024, 5, 14, 10, 0, 0, tzinfo=timezone.utc)

BASELINE_METRICS: dict[str, object] = {
    "cpu": 35.2,
    "memory": 47.8,
    "db_connections": 20,
    "db_connection_limit": 100,
    "db_latency_ms": 18,
    "redis_health": "healthy",
    "request_rate": 120,
    "http_5xx_rate": 0.2,
    "p50_latency_ms": 80,
    "p95_latency_ms": 125,
    "p99_latency_ms": 210,
    "dependency_latency_ms": 35,
    "queue_depth": 5,
    "deployment_status": "healthy",
    "deployment_version": "1.4.2",
    "disk_utilization": 42,
}

FAULTS = (
    "db_pool_exhaustion",
    "bad_deployment",
    "memory_leak",
    "redis_failure",
    "dependency_timeout",
    "traffic_spike",
    "cache_stampede",
    "disk_exhaustion",
)

ACTIONS = (
    "rollback_deployment",
    "restart_service",
    "clear_db_connections",
    "restart_redis",
    "restore_dependency",
    "scale_service",
    "clear_queue",
    "free_disk",
)

# Which faults each action resolves. Anything else leaves state unchanged
# (except clear_queue, which drains the queue but does not clear a fault).
ACTION_REMEDIES: dict[str, tuple[str, ...]] = {
    "rollback_deployment": ("bad_deployment",),
    "restart_service": ("memory_leak", "cache_stampede"),
    "clear_db_connections": ("db_pool_exhaustion",),
    "restart_redis": ("redis_failure",),
    "restore_dependency": ("dependency_timeout",),
    "scale_service": ("traffic_spike",),
    "clear_queue": (),
    "free_disk": ("disk_exhaustion",),
}

ACTION_RESULTS: dict[str, str] = {
    "rollback_deployment": "deployment rolled back to version 1.4.2",
    "restart_service": "payment-api restarted, runtime state cleared",
    "clear_db_connections": "database connection pool recovered",
    "restart_redis": "redis cache restarted and reachable",
    "restore_dependency": "downstream dependency responding normally",
    "scale_service": "additional payment-api replicas online, load distributed",
    "clear_queue": "pending queue drained",
    "free_disk": "disk space reclaimed, old logs rotated",
}

FAULT_LOGS: dict[str, tuple[str, ...]] = {
    "db_pool_exhaustion": (
        "ERROR payment request failed: database connection unavailable",
        "WARN connection acquisition exceeded timeout (850ms)",
        "WARN db pool saturated: 100/100 connections in use",
        "ERROR transaction request returned 503",
    ),
    "bad_deployment": (
        "INFO deployment v1.5.0 completed",
        "ERROR unhandled exception processing payment (v1.5.0)",
        "ERROR transaction request returned 500",
        "WARN elevated error rate detected",
    ),
    "memory_leak": (
        "WARN heap usage above 85% threshold",
        "WARN garbage collection taking too long",
        "ERROR payment request timed out after 2000ms",
    ),
    "redis_failure": (
        "ERROR redis connection refused",
        "WARN cache unavailable, falling back to database",
        "ERROR payment request failed: cache timeout",
        "ERROR transaction request returned 503",
    ),
    "dependency_timeout": (
        "ERROR fraud-check dependency timed out after 4000ms",
        "WARN dependency latency above SLO",
        "ERROR transaction request returned 504",
    ),
    "traffic_spike": (
        "WARN request rate above autoscale threshold",
        "WARN queue depth growing",
        "INFO CPU above 90%",
        "ERROR transaction request returned 503 (overload)",
    ),
    "cache_stampede": (
        "WARN cache hit ratio dropping",
        "WARN thundering herd on hot keys, backend load rising",
        "WARN database load increasing",
        "ERROR payment request timed out",
    ),
    "disk_exhaustion": (
        "WARN disk utilization above 95%",
        "ERROR failed to write transaction log: no space left on device",
        "ERROR transaction request returned 500",
    ),
}

BASELINE_LOGS: tuple[str, ...] = (
    "INFO payment-api v1.4.2 started, listening on :8080",
    "INFO connected to database pool (20/100)",
    "INFO redis cache connected",
    "INFO health check passed",
)

_MAX_LOGS = 200


class UnknownFaultError(ValueError):
    """Raised when injecting a fault name the simulator does not define."""


class UnknownActionError(ValueError):
    """Raised when executing an action the simulator does not define."""


class PaymentSimulator:
    """Deterministic in-memory payment-api. Single instance per process."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> dict[str, object]:
        self._metrics: dict[str, object] = dict(BASELINE_METRICS)
        self._active_fault: str | None = None
        self._clock = 0
        self._txn_counter = 0
        self._leak_progress = 0
        self._logs: list[str] = []
        for line in BASELINE_LOGS:
            self._append_log(line)
        return {"status": "reset", "service": "payment-api"}

    # -- internal helpers -------------------------------------------------

    def _timestamp(self) -> str:
        self._clock += 1
        return (BASE_TIME + timedelta(seconds=self._clock)).isoformat()

    def _append_log(self, line: str) -> None:
        self._logs.append(f"{self._timestamp()} {line}")
        if len(self._logs) > _MAX_LOGS:
            self._logs = self._logs[-_MAX_LOGS:]

    def _apply(self, overrides: dict[str, object]) -> None:
        self._metrics.update(overrides)

    # -- observation (agent-facing) ---------------------------------------

    def get_health(self) -> dict[str, object]:
        return {
            "service": "payment-api",
            "environment": "production",
            "status": "healthy" if self._active_fault is None else "degraded",
        }

    def get_metrics(self) -> dict[str, object]:
        if self._active_fault == "memory_leak":
            self._leak_progress = min(self._leak_progress + 1, 10)
            step = self._leak_progress
            self._apply(
                {
                    "memory": round(min(84.0 + 1.1 * step, 96.5), 1),
                    "cpu": round(min(55.0 + 2.0 * step, 78.0), 1),
                    "http_5xx_rate": round(min(4.0 + 0.8 * step, 12.0), 1),
                    "p95_latency_ms": min(400 + 120 * step, 1600),
                    "p99_latency_ms": min(700 + 200 * step, 2800),
                }
            )
        return dict(self._metrics)

    def get_state(self) -> dict[str, object]:
        metrics = self._metrics
        return {
            "service": "payment-api",
            "status": "healthy" if self._active_fault is None else "degraded",
            "deployment": {
                "version": metrics["deployment_version"],
                "status": metrics["deployment_status"],
            },
            "db_pool": {
                "used": metrics["db_connections"],
                "limit": metrics["db_connection_limit"],
                "status": "saturated"
                if metrics["db_connections"] >= metrics["db_connection_limit"]
                else "ok",
            },
            "redis": {"status": metrics["redis_health"]},
            "queue": {
                "depth": metrics["queue_depth"],
                "status": "backlogged" if metrics["queue_depth"] > 50 else "ok",  # type: ignore[operator]
            },
            "disk": {
                "utilization_percent": metrics["disk_utilization"],
                "status": "full" if metrics["disk_utilization"] >= 95 else "ok",  # type: ignore[operator]
            },
        }

    def get_logs(self, limit: int = 50) -> dict[str, object]:
        return {"service": "payment-api", "logs": self._logs[-limit:]}

    def get_snapshot(self) -> dict[str, object]:
        return {
            "health": self.get_health(),
            "metrics": self.get_metrics(),
            "state": self.get_state(),
            "logs": self._logs[-20:],
        }

    def process_transaction(self) -> dict[str, object]:
        """Simulate one payment request; outcome follows current 5xx rate."""
        self._txn_counter += 1
        if self._active_fault == "memory_leak":
            self._leak_progress = min(self._leak_progress + 1, 10)
        error_rate = float(self._metrics["http_5xx_rate"])  # percent
        failed = (self._txn_counter % 100) < error_rate
        p50 = int(self._metrics["p50_latency_ms"])
        p95 = int(self._metrics["p95_latency_ms"])
        latency = p50 + (self._txn_counter * 7) % max(p95 - p50, 1)
        if not failed:
            return {"status": "success", "status_code": 200, "latency_ms": latency}
        code = 504 if self._active_fault == "dependency_timeout" else 503
        self._append_log(f"ERROR transaction request returned {code}")
        return {"status": "failed", "status_code": code, "latency_ms": latency}

    # -- fault injection (evaluation harness) ------------------------------

    def inject_fault(self, fault_type: str) -> dict[str, object]:
        if fault_type not in FAULTS:
            raise UnknownFaultError(f"Unknown fault: {fault_type}")
        self.reset()
        self._active_fault = fault_type
        applier = getattr(self, f"_fault_{fault_type}")
        applier()
        for line in FAULT_LOGS[fault_type]:
            self._append_log(line)
        return {"status": "fault_injected", "service": "payment-api"}

    def _fault_db_pool_exhaustion(self) -> None:
        self._apply(
            {
                "db_connections": 100,
                "db_latency_ms": 900,
                "http_5xx_rate": 25.0,
                "p50_latency_ms": 600,
                "p95_latency_ms": 2400,
                "p99_latency_ms": 4100,
                "cpu": 45.0,
                "queue_depth": 60,
            }
        )

    def _fault_bad_deployment(self) -> None:
        self._apply(
            {
                "deployment_version": "1.5.0",
                "deployment_status": "just_deployed",
                "http_5xx_rate": 18.0,
                "p50_latency_ms": 400,
                "p95_latency_ms": 1800,
                "p99_latency_ms": 2900,
                "cpu": 55.0,
                "memory": 52.0,
            }
        )

    def _fault_memory_leak(self) -> None:
        self._leak_progress = 0
        self._apply(
            {
                "memory": 84.0,
                "cpu": 55.0,
                "http_5xx_rate": 4.0,
                "p50_latency_ms": 200,
                "p95_latency_ms": 400,
                "p99_latency_ms": 700,
            }
        )

    def _fault_redis_failure(self) -> None:
        self._apply(
            {
                "redis_health": "unavailable",
                "http_5xx_rate": 14.0,
                "p50_latency_ms": 300,
                "p95_latency_ms": 1500,
                "p99_latency_ms": 2600,
                "cpu": 60.0,
                "db_connections": 45,
                "db_latency_ms": 120,
            }
        )

    def _fault_dependency_timeout(self) -> None:
        self._apply(
            {
                "dependency_latency_ms": 4500,
                "http_5xx_rate": 22.0,
                "p50_latency_ms": 900,
                "p95_latency_ms": 5200,
                "p99_latency_ms": 8000,
                "cpu": 40.0,
            }
        )

    def _fault_traffic_spike(self) -> None:
        self._apply(
            {
                "request_rate": 1450,
                "cpu": 92.0,
                "queue_depth": 480,
                "p50_latency_ms": 500,
                "p95_latency_ms": 1900,
                "p99_latency_ms": 3400,
                "http_5xx_rate": 9.0,
                "memory": 68.0,
                "db_connections": 85,
            }
        )

    def _fault_cache_stampede(self) -> None:
        self._apply(
            {
                "request_rate": 380,
                "cpu": 84.0,
                "db_connections": 96,
                "db_latency_ms": 640,
                "http_5xx_rate": 12.0,
                "p50_latency_ms": 450,
                "p95_latency_ms": 2100,
                "p99_latency_ms": 3600,
                "memory": 70.0,
                "redis_health": "degraded",
            }
        )

    def _fault_disk_exhaustion(self) -> None:
        self._apply(
            {
                "disk_utilization": 98.5,
                "http_5xx_rate": 7.0,
                "p50_latency_ms": 250,
                "p95_latency_ms": 900,
                "p99_latency_ms": 1500,
                "cpu": 48.0,
                "queue_depth": 40,
            }
        )

    # -- controlled actions -------------------------------------------------

    def execute_action(self, action: str) -> dict[str, object]:
        if action not in ACTIONS:
            raise UnknownActionError(f"Unknown action: {action}")
        if action == "clear_queue":
            self._metrics["queue_depth"] = BASELINE_METRICS["queue_depth"]
            self._append_log("INFO pending queue drained by operator action")
            return {
                "action": action,
                "status": "executed",
                "result": ACTION_RESULTS[action],
            }
        remedies = ACTION_REMEDIES[action]
        if self._active_fault in remedies:
            self._active_fault = None
            self._leak_progress = 0
            self._metrics = dict(BASELINE_METRICS)
            self._append_log(f"INFO operator action completed: {action}")
            return {
                "action": action,
                "status": "executed",
                "result": ACTION_RESULTS[action],
            }
        return {
            "action": action,
            "status": "executed",
            "result": "no significant change observed",
        }

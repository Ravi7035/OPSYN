"""Agent tool layer: controlled interface between the agent and simulator.

The agent must NEVER touch ``PaymentSimulator`` internals directly.
Every observation and action goes through :class:`AgentTools`, which
wraps simulator outputs in a structured :class:`ToolResult` and strips
any hidden evaluation state before the agent can see it.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict, Field

from app.services.payment_simulator import ACTIONS, PaymentSimulator

logger = logging.getLogger(__name__)

OBSERVATION_TOOLS: tuple[str, ...] = (
    "get_health",
    "get_metrics",
    "get_state",
    "get_logs",
    "get_snapshot",
)

ACTION_TOOLS: tuple[str, ...] = tuple(ACTIONS)

# Keys that must never reach the agent, even if a future simulator
# refactor accidentally includes them in a response payload.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "active_fault",
        "_active_fault",
        "expected_action",
        "root_cause",
        "fault_type",
        "fault_injection",
        "fault",
    }
)


class ToolResult(BaseModel):
    """Structured outcome of one tool call."""

    model_config = ConfigDict(extra="ignore")

    tool: str = Field(description="Tool name that was executed")
    success: bool = Field(default=True)
    data: dict = Field(default_factory=dict)
    summary: str = Field(default="")
    error: str | None = Field(default=None)


def sanitize_payload(payload: object) -> object:
    """Recursively remove forbidden keys from agent-facing data."""
    if isinstance(payload, dict):
        return {
            key: sanitize_payload(value)
            for key, value in payload.items()
            if key not in FORBIDDEN_KEYS
        }
    if isinstance(payload, (list, tuple)):
        return [sanitize_payload(item) for item in payload]
    return payload


def assert_no_hidden_state(payload: object) -> None:
    """Defensive check: fail loudly if hidden state would leak to agent."""
    blob = json.dumps(payload, default=str)
    lowered = blob.lower()
    for secret in ("active_fault", "expected_action", "root_cause"):
        if secret in lowered:
            raise ValueError(f"Hidden simulator state leaked: {secret}")


class AgentTools:
    """Owns the only reference to the simulator the agent may use."""

    def __init__(self, simulator: PaymentSimulator) -> None:
        self._simulator = simulator

    # -- registry ------------------------------------------------------

    def list_observation_tools(self) -> list[str]:
        return list(OBSERVATION_TOOLS)

    def list_action_tools(self) -> list[str]:
        return list(ACTION_TOOLS)

    # -- internal ------------------------------------------------------

    def _wrap(self, tool: str, raw: dict[str, object], summary: str) -> ToolResult:
        clean = sanitize_payload(raw)
        assert isinstance(clean, dict)
        assert_no_hidden_state(clean)
        return ToolResult(tool=tool, success=True, data=clean, summary=summary)

    # -- observations --------------------------------------------------

    async def get_health(self) -> ToolResult:
        raw = self._simulator.get_health()
        status = str(raw.get("status", "unknown"))
        result = self._wrap(
            "get_health", raw, f"service status={status}"
        )
        logger.info("OBSERVATION tool=get_health summary=%s", result.summary)
        return result

    async def get_metrics(self) -> ToolResult:
        raw = self._simulator.get_metrics()
        summary = (
            f"5xx={raw.get('http_5xx_rate')} cpu={raw.get('cpu')} "
            f"mem={raw.get('memory')} db={raw.get('db_connections')}/"
            f"{raw.get('db_connection_limit')} dblat={raw.get('db_latency_ms')}ms"
        )
        result = self._wrap("get_metrics", raw, summary)
        logger.info("OBSERVATION tool=get_metrics summary=%s", result.summary)
        return result

    async def get_state(self) -> ToolResult:
        raw = self._simulator.get_state()
        result = self._wrap("get_state", raw, f"state={raw.get('status')}")
        logger.info("OBSERVATION tool=get_state summary=%s", result.summary)
        return result

    async def get_logs(self, limit: int = 50) -> ToolResult:
        raw = self._simulator.get_logs(limit=limit)
        logs = raw.get("logs")
        count = len(logs) if isinstance(logs, list) else 0
        result = self._wrap("get_logs", raw, f"{count} log lines")
        logger.info("OBSERVATION tool=get_logs summary=%s", result.summary)
        return result

    async def get_snapshot(self) -> ToolResult:
        raw = self._simulator.get_snapshot()
        metrics = raw.get("metrics")
        five_xx: object = "?"
        if isinstance(metrics, dict):
            five_xx = metrics.get("http_5xx_rate", "?")
        result = self._wrap(
            "get_snapshot", raw, f"snapshot captured, 5xx={five_xx}"
        )
        logger.info("OBSERVATION tool=get_snapshot summary=%s", result.summary)
        return result

    # -- actions --------------------------------------------------------

    async def execute_action(self, action: str) -> ToolResult:
        if action not in ACTION_TOOLS:
            return ToolResult(
                tool=action,
                success=False,
                data={},
                summary=f"unknown action: {action}",
                error=f"Unknown action: {action}",
            )
        raw = self._simulator.execute_action(action)
        result_text = str(raw.get("result", ""))
        result = self._wrap(action, raw, result_text)
        logger.info("ACTION_EXECUTED action=%s result=%s", action, result_text)
        return result

    async def run_tool(self, tool: str, target: str | None = None) -> ToolResult:
        """Generic dispatch used by the agent loop."""
        _ = target  # reserved for future scoped tools; currently unused.
        if tool == "get_health":
            return await self.get_health()
        if tool == "get_metrics":
            return await self.get_metrics()
        if tool == "get_state":
            return await self.get_state()
        if tool == "get_logs":
            return await self.get_logs()
        if tool == "get_snapshot":
            return await self.get_snapshot()
        if tool in ACTION_TOOLS:
            return await self.execute_action(tool)
        return ToolResult(
            tool=tool,
            success=False,
            data={},
            summary=f"unknown tool: {tool}",
            error=f"Unknown tool: {tool}",
        )

"""OPSYN incident-response agent core.

Orchestrates: Observe → Recall → Hypothesize → Investigate → Act →
Verify → Learn → Retain. Fault-specific rules live in the reasoning
model; this module owns the loop, state, verification, and learning.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from app.models.incident import (
    AgentAction,
    EvidenceItem,
    Hypothesis,
    Incident,
    IncidentSource,
    InvestigationStep,
    Learning,
    Verification,
)
from app.services.agent_tools import AgentTools, ToolResult
from app.services.reasoning_model import (
    AgentState,
    DeterministicReasoningModel,
    ReasoningModel,
)

logger = logging.getLogger(__name__)

# Optional lifecycle hook for operator-side incident records:
# ``on_stage(stage, context)`` is invoked with INVESTIGATING /
# REMEDIATING / VERIFYING plus small observable summaries. It never
# influences reasoning, tools, or verification — pass None to disable.
StageCallback = Callable[[str, dict[str, object]], None]

MAX_INVESTIGATION_STEPS = 10
MAX_ACTIONS = 3

BASELINE_OBSERVATIONS: tuple[str, ...] = (
    "get_health",
    "get_metrics",
    "get_state",
    "get_logs",
)

NUMERIC_METRIC_KEYS: tuple[str, ...] = (
    "cpu",
    "memory",
    "db_connections",
    "db_latency_ms",
    "http_5xx_rate",
    "p50_latency_ms",
    "p95_latency_ms",
    "dependency_latency_ms",
    "request_rate",
    "queue_depth",
    "disk_utilization",
)


class InMemoryHindsight:
    """Fallback memory when Hindsight Cloud is not configured.

    Keyword-overlap recall over locally retained incidents. Keeps the
    agent (and its tests) fully deterministic with no API key/network.
    """

    def __init__(self) -> None:
        self._store: list[dict] = []

    async def retain_incident(self, incident: Incident) -> dict[str, object]:
        self._store.append(
            {
                "incident_id": incident.incident_id,
                "text": incident.to_memory_text(),
                "context": incident.to_memory_context(),
            }
        )
        return {"incident_id": incident.incident_id, "success": True, "local": True}

    async def recall_incidents(
        self, query: str, max_tokens: int = 4096
    ) -> list[dict[str, object]]:
        _ = max_tokens
        if not query.strip():
            raise ValueError("Recall query must not be empty.")
        query_words = {w.lower() for w in query.split() if len(w) > 3}
        scored: list[tuple[int, dict]] = []
        for entry in self._store:
            text_words = {w.lower() for w in entry["text"].split()}
            overlap = len(query_words & text_words)
            scored.append((overlap, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"text": entry["text"], "score": float(overlap), "metadata": {"incident_id": entry["incident_id"]}}
            for overlap, entry in scored[:3]
        ]

    @property
    def retained_count(self) -> int:
        return len(self._store)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _memory_ids(memories: list[dict]) -> list[str]:
    """Best-effort recalled memory identifiers (operator metadata only)."""
    ids: list[str] = []
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        metadata = memory.get("metadata")
        if isinstance(metadata, dict):
            memory_id = metadata.get("incident_id")
            if isinstance(memory_id, str) and memory_id not in ids:
                ids.append(memory_id)
    return ids


class IncidentResponseAgent:
    """Runs the bounded incident-response loop for one incident."""

    def __init__(
        self,
        reasoning_model: ReasoningModel | None = None,
        tools: AgentTools | None = None,
        hindsight: object | None = None,
        max_investigation_steps: int = MAX_INVESTIGATION_STEPS,
        max_actions: int = MAX_ACTIONS,
    ) -> None:
        self._reasoning: ReasoningModel = (
            reasoning_model or DeterministicReasoningModel()
        )
        self._tools = tools
        self._hindsight = hindsight
        self._max_steps = max_investigation_steps
        self._max_actions = max_actions

    # -- public ---------------------------------------------------------

    async def run(
        self,
        incident: Incident,
        on_stage: StageCallback | None = None,
    ) -> Incident:
        if self._tools is None:
            raise ValueError("IncidentResponseAgent requires AgentTools.")
        logger.info(
            "INCIDENT_STARTED incident=%s service=%s",
            incident.incident_id,
            incident.service,
        )
        observations: dict = {}
        observation_history: list[dict] = []
        recalled_memories: list[dict] = []
        tools_used: list[str] = []
        failed_actions: list[str] = []
        successful_actions: list[str] = []
        step_seq = len(incident.investigation)
        action_seq = len(incident.actions)

        # -- Observe (baseline) -----------------------------------------
        for tool_name in BASELINE_OBSERVATIONS:
            result = await self._tools.run_tool(tool_name)
            step_seq += 1
            self._record_observation(incident, result, step_seq, observations)
            tools_used.append(tool_name)
            if tool_name == "get_metrics" and isinstance(result.data, dict):
                observation_history.append(dict(result.data))

        # -- Recall ------------------------------------------------------
        recalled_memories = await self._recall(incident, observations)
        logger.info("MEMORY_RECALL count=%d", len(recalled_memories))

        # -- Hypothesize -------------------------------------------------
        incident.hypotheses = self._reasoning.evaluate_hypotheses(
            observations, recalled_memories, observation_history, failed_actions
        )
        self._emit_stage(
            on_stage,
            "INVESTIGATING",
            {
                "recalled_memory_count": len(recalled_memories),
                "recalled_memory_ids": _memory_ids(recalled_memories),
                "hypotheses": len(incident.hypotheses),
            },
        )
        for hypothesis in incident.hypotheses:
            logger.info(
                "HYPOTHESIS_CREATED statement=%s status=%s confidence=%s",
                hypothesis.statement,
                hypothesis.status,
                hypothesis.confidence,
            )

        # -- Investigate / Act loop --------------------------------------
        while len(incident.investigation) < self._max_steps:
            state = AgentState(
                incident_id=incident.incident_id,
                observations=observations,
                observation_history=observation_history,
                recalled_memories=recalled_memories,
                investigation_count=len(incident.investigation),
                action_count=len(incident.actions),
                failed_actions=list(failed_actions),
                successful_actions=list(successful_actions),
                tools_used=list(tools_used),
                hypotheses=[h.model_dump() for h in incident.hypotheses],
                action_results=[
                    {
                        "action": a.action,
                        "status": a.status,
                        "result": a.result,
                    }
                    for a in incident.actions
                ],
                verification=(
                    incident.verification.model_dump()
                    if incident.verification is not None
                    else None
                ),
            )
            decision = self._reasoning.choose_next_step(state)

            if decision.type in ("observe", "investigate"):
                tool_name = decision.tool or "get_snapshot"
                result = await self._tools.run_tool(tool_name, decision.target)
                step_seq += 1
                self._record_observation(incident, result, step_seq, observations)
                tools_used.append(tool_name)
                if tool_name in ("get_metrics", "get_snapshot"):
                    metrics = self._latest_metrics(observations)
                    if metrics:
                        observation_history.append(dict(metrics))
                incident.hypotheses = self._refresh_hypotheses(
                    incident.hypotheses,
                    observations,
                    recalled_memories,
                    observation_history,
                    failed_actions,
                )
                continue

            if decision.type == "act":
                if len(incident.actions) >= self._max_actions:
                    logger.info(
                        "INCIDENT_ESCALATED reason=action budget exhausted"
                    )
                    break
                action_name = decision.action or ""
                if action_name in failed_actions:
                    logger.info(
                        "ACTION_PROPOSED action=%s skipped (already failed "
                        "without new evidence)",
                        action_name,
                    )
                    break
                action_seq += 1
                self._emit_stage(on_stage, "REMEDIATING", {"action": action_name})
                resolved = await self._execute_and_verify(
                    incident,
                    action_name,
                    action_seq,
                    observations,
                    failed_actions,
                    successful_actions,
                    on_stage=on_stage,
                )
                if not resolved:
                    # Re-evaluate against still-degraded observations; on success
                    # the pre-action hypotheses (with the "selected" marker)
                    # are the meaningful record, not healthy post-fix metrics.
                    incident.hypotheses = self._refresh_hypotheses(
                        incident.hypotheses,
                        observations,
                        recalled_memories,
                        observation_history,
                        failed_actions,
                    )
                metrics = self._latest_metrics(observations)
                if metrics:
                    observation_history.append(dict(metrics))
                if resolved:
                    incident.learning = self._build_learning(
                        incident, "resolved", successful_actions, failed_actions
                    )
                    logger.info("LEARNING_CREATED outcome=resolved")
                    logger.info("INCIDENT_RESOLVED incident=%s", incident.incident_id)
                    await self._retain(incident)
                    return incident
                continue

            # finish / escalate
            logger.info(
                "INCIDENT_ESCALATED reason=%s", decision.reasoning or decision.type
            )
            break

        # -- Unresolved path ----------------------------------------------
        if incident.verification is None:
            incident.verification = Verification(
                metrics_before={},
                metrics_after=self._latest_metrics(observations) or {},
                improved=False,
                status="unresolved",
            )
        outcome = "escalated" if len(incident.actions) >= self._max_actions else "unresolved"
        # Escalation and exhaustion-of-budget are both non-resolved endings;
        # normalize to values the Learning model documents.
        if incident.verification.status == "pending":
            incident.verification.status = outcome
        incident.learning = self._build_learning(
            incident, outcome, successful_actions, failed_actions
        )
        logger.info("LEARNING_CREATED outcome=%s", outcome)
        logger.info("INCIDENT_ESCALATED incident=%s", incident.incident_id)
        await self._retain(incident)
        return incident

    # -- observation recording --------------------------------------------

    def _record_observation(
        self,
        incident: Incident,
        result: ToolResult,
        step_seq: int,
        observations: dict,
    ) -> None:
        observations[result.tool] = result.data
        if result.tool == "get_snapshot" and isinstance(result.data, dict):
            for key in ("health", "metrics", "state"):
                if key not in observations and key in result.data:
                    observations[key] = result.data[key]
            if "logs" not in observations and isinstance(result.data.get("logs"), list):
                observations["logs"] = {"logs": result.data["logs"]}
        evidence = self._evidence_from_tool(result)
        incident.evidence.extend(evidence)
        incident.investigation.append(
            InvestigationStep(
                step_id=f"step-{step_seq}",
                started_at=_now(),
                tool=result.tool,
                target=None,
                result_summary=result.summary[:500],
                result_refs=[item.signal for item in evidence[:8]],
            )
        )
        logger.info(
            "OBSERVATION tool=%s summary=%s", result.tool, result.summary
        )

    def _evidence_from_tool(self, result: ToolResult) -> list[EvidenceItem]:
        now = _now()
        items: list[EvidenceItem] = []
        data = result.data if isinstance(result.data, dict) else {}
        if result.tool in ("get_metrics", "get_snapshot"):
            metrics = data.get("metrics") if result.tool == "get_snapshot" else data
            if not isinstance(metrics, dict):
                metrics = {}
            used = metrics.get("db_connections")
            limit = metrics.get("db_connection_limit", 100)
            items.append(
                EvidenceItem(
                    signal="db_connections",
                    value=f"{used}/{limit}",
                    observed_at=now,
                    provenance="observed",
                    stance="neutral",
                )
            )
            for key in (
                "db_latency_ms",
                "http_5xx_rate",
                "cpu",
                "memory",
                "redis_health",
                "dependency_latency_ms",
                "request_rate",
                "queue_depth",
                "disk_utilization",
                "deployment_version",
                "deployment_status",
                "p95_latency_ms",
            ):
                if key in metrics:
                    items.append(
                        EvidenceItem(
                            signal=key,
                            value=str(metrics[key]),
                            observed_at=now,
                            provenance="observed",
                            stance="neutral",
                        )
                    )
        elif result.tool == "get_health":
            items.append(
                EvidenceItem(
                    signal="service_status",
                    value=str(data.get("status", "unknown")),
                    observed_at=now,
                    provenance="observed",
                    stance="neutral",
                )
            )
        elif result.tool == "get_state":
            for section in ("deployment", "db_pool", "redis", "queue", "disk"):
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    items.append(
                        EvidenceItem(
                            signal=f"state.{section}",
                            value=str(section_data),
                            observed_at=now,
                            provenance="observed",
                            stance="neutral",
                        )
                    )
            if "status" in data:
                items.append(
                    EvidenceItem(
                        signal="state.status",
                        value=str(data["status"]),
                        observed_at=now,
                        provenance="observed",
                        stance="neutral",
                    )
                )
        elif result.tool == "get_logs":
            logs = data.get("logs")
            if isinstance(logs, list):
                interesting = [
                    line for line in logs if isinstance(line, str)
                    and ("ERROR" in line or "WARN" in line)
                ][-5:]
                for line in interesting:
                    items.append(
                        EvidenceItem(
                            signal="log",
                            value=str(line)[-300:],
                            observed_at=now,
                            provenance="observed",
                            stance="neutral",
                        )
                    )
        if not items:
            items.append(
                EvidenceItem(
                    signal=f"tool.{result.tool}",
                    value=result.summary[:300],
                    observed_at=now,
                    provenance="observed",
                    stance="neutral",
                )
            )
        return items

    # -- hindsight ----------------------------------------------------------

    def _recall_query(self, incident: Incident, observations: dict) -> str:
        parts = [
            f"sre incident in {incident.service}",
            "; ".join(incident.symptoms) if incident.symptoms else "",
        ]
        metrics = observations.get("metrics")
        if isinstance(metrics, dict):
            parts.append(
                "observed metrics: "
                + ", ".join(
                    f"{k}={metrics[k]}"
                    for k in (
                        "http_5xx_rate",
                        "db_connections",
                        "db_latency_ms",
                        "cpu",
                        "memory",
                        "redis_health",
                        "dependency_latency_ms",
                        "request_rate",
                        "queue_depth",
                        "disk_utilization",
                    )
                    if k in metrics
                )
            )
        return " ".join(p for p in parts if p).strip() or f"sre incident {incident.service}"

    async def _recall(
        self, incident: Incident, observations: dict
    ) -> list[dict[str, object]]:
        if self._hindsight is None:
            return []
        query = self._recall_query(incident, observations)
        recall = getattr(self._hindsight, "recall_incidents", None)
        if recall is None:
            return []
        try:
            memories = await recall(query)
            return list(memories) if isinstance(memories, list) else []
        except Exception as exc:  # memory must never break response
            logger.warning("MEMORY_RECALL_FAILED error=%s", type(exc).__name__)
            return []

    async def _retain(self, incident: Incident) -> None:
        learning = incident.learning
        if learning is None or not learning.suitable_for_hindsight:
            return
        if self._hindsight is None:
            return
        retain = getattr(self._hindsight, "retain_incident", None)
        if retain is None:
            return
        try:
            await retain(incident)
            logger.info("HINDSIGHT_RETAINED incident=%s", incident.incident_id)
        except Exception as exc:
            logger.warning("HINDSIGHT_RETAIN_FAILED error=%s", type(exc).__name__)

    # -- hypotheses -----------------------------------------------------------

    @staticmethod
    def _emit_stage(
        on_stage: StageCallback | None,
        stage: str,
        context: dict[str, object] | None = None,
    ) -> None:
        """Notify an operator-side lifecycle listener. Never affects reasoning."""
        if on_stage is None:
            return
        try:
            on_stage(stage, dict(context or {}))
        except Exception as exc:  # lifecycle listeners must never break runs
            logger.warning("STAGE_LISTENER_FAILED stage=%s error=%s", stage, exc)

    def _refresh_hypotheses(
        self,
        current: list[Hypothesis],
        observations: dict,
        memories: list[dict],
        history: list[dict],
        failed_actions: list[str],
    ) -> list[Hypothesis]:
        fresh = self._reasoning.evaluate_hypotheses(
            observations, memories, history, failed_actions
        )
        previous_by_statement = {h.statement: h for h in current}
        for hypothesis in fresh:
            previous = previous_by_statement.get(hypothesis.statement)
            if previous is None:
                logger.info(
                    "HYPOTHESIS_CREATED statement=%s status=%s confidence=%s",
                    hypothesis.statement,
                    hypothesis.status,
                    hypothesis.confidence,
                )
            elif previous.status != hypothesis.status:
                event = (
                    "HYPOTHESIS_REJECTED"
                    if hypothesis.status == "rejected"
                    else "HYPOTHESIS_SUPPORTED"
                    if hypothesis.status == "supported"
                    else "HYPOTHESIS_CREATED"
                )
                logger.info(
                    "%s statement=%s %s->%s confidence=%s",
                    event,
                    hypothesis.statement,
                    previous.status,
                    hypothesis.status,
                    hypothesis.confidence,
                )
        # Preserve any "selected" marker for the hypothesis we acted on.
        selected = {h.statement for h in current if h.status == "selected"}
        for hypothesis in fresh:
            if hypothesis.statement in selected and hypothesis.status == "supported":
                hypothesis.status = "selected"
        return fresh

    # -- action + verification --------------------------------------------------

    def _latest_metrics(self, observations: dict) -> dict[str, float]:
        metrics = observations.get("metrics")
        if not isinstance(metrics, dict):
            snapshot = observations.get("snapshot")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("metrics"), dict):
                metrics = snapshot["metrics"]
            else:
                return {}
        result: dict[str, float] = {}
        for key in NUMERIC_METRIC_KEYS:
            value = _to_float(metrics.get(key))
            if value is not None:
                result[key] = value
        return result

    async def _execute_and_verify(
        self,
        incident: Incident,
        action_name: str,
        action_seq: int,
        observations: dict,
        failed_actions: list[str],
        successful_actions: list[str],
        on_stage: StageCallback | None = None,
    ) -> bool:
        metrics_before = self._latest_metrics(observations)
        logger.info("ACTION_PROPOSED action=%s", action_name)
        result = await self._tools.run_tool(action_name)  # type: ignore[union-attr]
        action_id = f"action-{action_seq}"
        improved_text = str(result.summary or "")
        no_change = "no significant change" in improved_text.lower()

        # Re-observe after the action.
        health_after = await self._tools.run_tool("get_health")  # type: ignore[union-attr]
        metrics_after_result = await self._tools.run_tool("get_metrics")  # type: ignore[union-attr]
        observations["health"] = health_after.data
        observations["metrics"] = metrics_after_result.data
        self._record_post_action_evidence(incident, health_after, metrics_after_result)

        metrics_after = self._latest_metrics(observations)
        before_5xx = metrics_before.get("http_5xx_rate", 0.0)
        after_5xx = metrics_after.get("http_5xx_rate", before_5xx)
        health_status = (
            health_after.data.get("status")
            if isinstance(health_after.data, dict)
            else "unknown"
        )
        resolved = bool(
            not no_change
            and health_status == "healthy"
            and after_5xx < 1.0
        )
        improved = bool(
            not no_change
            and (resolved or after_5xx <= before_5xx * 0.7)
        )
        status = "resolved" if resolved else ("improved" if improved else "no_improvement")

        incident.actions.append(
            AgentAction(
                action_id=action_id,
                action=action_name,
                target=incident.service,
                status="executed",
                executed_at=_now(),
                result=f"{improved_text} | 5xx {before_5xx}->{after_5xx} | {status}",
            )
        )
        incident.verification = Verification(
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            improved=improved,
            status="resolved" if resolved else "pending",
        )
        self._emit_stage(
            on_stage,
            "VERIFYING",
            {
                "action": action_name,
                "improved": improved,
                "status": incident.verification.status,
            },
        )
        logger.info(
            "ACTION_EXECUTED action=%s result=%s", action_name, improved_text
        )
        logger.info(
            "VERIFICATION action=%s before_5xx=%s after_5xx=%s improved=%s status=%s",
            action_name,
            before_5xx,
            after_5xx,
            improved,
            incident.verification.status,
        )
        # Mark selected hypothesis so retention shows what we acted on.
        for hypothesis in incident.hypotheses:
            from app.services.reasoning_model import HYPOTHESIS_ACTION as _MAP

            if _MAP.get(hypothesis.statement) == action_name and hypothesis.status in (
                "supported",
                "investigating",
                "considered",
            ):
                hypothesis.status = "selected" if resolved or improved else hypothesis.status
        if resolved or improved:
            successful_actions.append(action_name)
        else:
            failed_actions.append(action_name)
        return resolved

    def _record_post_action_evidence(
        self,
        incident: Incident,
        health: ToolResult,
        metrics: ToolResult,
    ) -> None:
        now = _now()
        if isinstance(health.data, dict):
            incident.evidence.append(
                EvidenceItem(
                    signal="service_status_post_action",
                    value=str(health.data.get("status", "unknown")),
                    observed_at=now,
                    provenance="observed",
                    stance="neutral",
                )
            )
        if isinstance(metrics.data, dict):
            for key in ("http_5xx_rate", "db_connections", "db_latency_ms"):
                if key in metrics.data:
                    incident.evidence.append(
                        EvidenceItem(
                            signal=f"{key}_post_action",
                            value=str(metrics.data[key]),
                            observed_at=now,
                            provenance="observed",
                            stance="neutral",
                        )
                    )

    # -- learning -----------------------------------------------------------------

    def _build_learning(
        self,
        incident: Incident,
        outcome: str,
        successful: list[str],
        failed: list[str],
    ) -> Learning:
        top = next(
            (h for h in incident.hypotheses if h.status in ("selected", "supported")),
            incident.hypotheses[0] if incident.hypotheses else None,
        )
        signals = []
        for item in incident.evidence:
            if item.signal in (
                "db_connections",
                "db_latency_ms",
                "http_5xx_rate",
                "state.deployment",
                "service_status",
                "redis_health",
                "dependency_latency_ms",
                "request_rate",
                "queue_depth",
                "disk_utilization",
                "memory",
                "cpu",
            ):
                signals.append(f"{item.signal}={item.value}")
        signal_text = "; ".join(signals[:8]) or "observed degradation signals"
        if outcome == "resolved" and top is not None:
            lesson = (
                f"{signal_text} indicated {top.statement}. "
                f"Executing {', '.join(successful) or 'the selected action'} "
                "restored service health (5xx < 1%, status healthy)."
            )
            if failed:
                lesson += (
                    f" Failed actions with no improvement: {', '.join(failed)}; "
                    "their hypotheses were down-weighted before retrying."
                )
        else:
            hypothesis_text = (
                "; ".join(
                    f"{h.statement} ({h.status}, confidence {h.confidence})"
                    for h in incident.hypotheses[:4]
                )
                or "no confident hypothesis"
            )
            lesson = (
                f"Investigation ended {outcome} after "
                f"{len(incident.investigation)} steps and "
                f"{len(incident.actions)} action(s). Hypotheses: {hypothesis_text}. "
                f"Signals: {signal_text}."
            )
            if successful:
                lesson += f" Successful actions: {', '.join(successful)}."
            if failed:
                lesson += (
                    f" Failed actions with no improvement: {', '.join(failed)}; "
                    "avoid repeating them for the same evidence pattern."
                )
        return Learning(
            outcome=outcome,
            successful_actions=list(successful),
            failed_actions=list(failed),
            lesson=lesson,
            suitable_for_hindsight=True,
        )


def new_incident_for_service(
    service: str = "payment-api",
    incident_id: str | None = None,
) -> Incident:
    return Incident(
        incident_id=incident_id or f"SIM-{uuid.uuid4().hex[:8]}",
        service=service,
        environment="production",
        source=IncidentSource.SIMULATOR,
        symptoms=["agent-initiated investigation"],
    )

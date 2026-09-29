"""Reasoning layer abstraction + deterministic stand-in for a future LLM.

``ReasoningModel`` is the interface the agent core programs against.
``DeterministicReasoningModel`` implements that interface with
transparent, observable-signal-only rules so the full incident-response
architecture can be validated without any LLM dependency.

The deterministic model NEVER receives hidden simulator state
(``active_fault`` / ``expected_action`` / ``root_cause``). It sees only:

- health / metrics / state / logs / snapshot observations
- Hindsight memories (treated as fallible evidence, never ground truth)
- previous investigation results, action results, verification results
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models.incident import Hypothesis

logger = logging.getLogger(__name__)

DecisionType = Literal["observe", "investigate", "act", "finish", "escalate"]

# Canonical hypothesis statements. The agent maps each to a registered
# action tool; keep these stable — tests and learning text rely on them.
HYPOTHESIS_DB_POOL = "DB pool exhaustion"
HYPOTHESIS_BAD_DEPLOY = "bad deployment"
HYPOTHESIS_MEM_LEAK = "memory leak"
HYPOTHESIS_REDIS = "redis failure"
HYPOTHESIS_DEP_TIMEOUT = "dependency timeout"
HYPOTHESIS_TRAFFIC = "traffic spike"
HYPOTHESIS_STAMPEDE = "cache stampede"
HYPOTHESIS_DISK = "disk exhaustion"

HYPOTHESIS_ACTION: dict[str, str] = {
    HYPOTHESIS_DB_POOL: "clear_db_connections",
    HYPOTHESIS_BAD_DEPLOY: "rollback_deployment",
    HYPOTHESIS_MEM_LEAK: "restart_service",
    HYPOTHESIS_REDIS: "restart_redis",
    HYPOTHESIS_DEP_TIMEOUT: "restore_dependency",
    HYPOTHESIS_TRAFFIC: "scale_service",
    HYPOTHESIS_STAMPEDE: "restart_service",
    HYPOTHESIS_DISK: "free_disk",
}

ACT_CONFIDENCE_THRESHOLD = 0.55
SUPPORTED_THRESHOLD = 0.60
REJECTED_THRESHOLD = 0.25


class ReasoningDecision(BaseModel):
    """One structured step chosen by the reasoning model."""

    model_config = ConfigDict(extra="ignore")

    type: DecisionType = Field(description="Kind of step to take next")
    tool: str | None = Field(default=None, description="Observation tool to run")
    action: str | None = Field(default=None, description="Remediation action to run")
    target: str | None = Field(default=None)
    reasoning: str = Field(default="")
    hypothesis: str | None = Field(default=None)
    confidence: float | None = Field(default=None)


@dataclass
class AgentState:
    """Everything the reasoner may legally consider.

    Deliberately contains NO hidden simulator fields — only observable
    evidence, recalled memories, and the agent's own history.
    """

    incident_id: str = ""
    observations: dict = field(default_factory=dict)
    observation_history: list[dict] = field(default_factory=list)
    recalled_memories: list[dict] = field(default_factory=list)
    investigation_count: int = 0
    action_count: int = 0
    failed_actions: list[str] = field(default_factory=list)
    successful_actions: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    # Previous reasoning context (populated by the agent; ignored by the
    # deterministic model). Observables only — never ground truth.
    hypotheses: list[dict] = field(default_factory=list)
    action_results: list[dict] = field(default_factory=list)
    verification: dict | None = None


class ReasoningModel(Protocol):
    """Interface the agent core depends on. An LLM plugs in here later."""

    def evaluate_hypotheses(
        self,
        observations: dict,
        memories: list[dict],
        observation_history: list[dict] | None = None,
        failed_actions: list[str] | None = None,
    ) -> list[Hypothesis]:
        ...

    def choose_next_step(self, state: AgentState) -> ReasoningDecision:
        ...


def _num(metrics: dict, key: str, default: float = 0.0) -> float:
    try:
        value = metrics.get(key, default)
        if isinstance(value, bool):
            return default
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _str(metrics: dict, key: str, default: str = "") -> str:
    value = metrics.get(key, default)
    return str(value) if value is not None else default


def _memory_mentions(memories: list[dict], *keywords: str) -> bool:
    for memory in memories:
        text = str(memory.get("text") or "")
        lowered = text.lower()
        if any(keyword.lower() in lowered for keyword in keywords):
            return True
    return False


# Phrases indicating a past action did NOT help. Used to treat historical
# failures as negative evidence: a memory that recalls an action failing
# must not boost the hypothesis that maps to that action.
_FAILURE_PHRASES: tuple[str, ...] = (
    "fail",
    "no improvement",
    "no significant change",
    "did not",
    "unsuccessful",
    "no effect",
    "without improvement",
)

_FAILURE_CONTEXT_WINDOW = 120


def _memory_recalls_action_failure(memories: list[dict], action: str) -> bool:
    """True when a memory mentions ``action`` near failure language.

    Proximity matters: a memory may record one action succeeding while a
    different action failed ("clear_db_connections restored health. Failed
    actions: restart_redis"). Only a failure phrase within
    ``_FAILURE_CONTEXT_WINDOW`` characters of the action mention counts.
    """
    if not action:
        return False
    for memory in memories or []:
        text = str((memory or {}).get("text") or "")
        lowered = text.lower()
        target = action.lower()
        start = 0
        while True:
            index = lowered.find(target, start)
            if index < 0:
                break
            snippet = lowered[
                max(0, index - _FAILURE_CONTEXT_WINDOW) : index
                + len(target)
                + _FAILURE_CONTEXT_WINDOW
            ]
            if any(phrase in snippet for phrase in _FAILURE_PHRASES):
                return True
            start = index + len(target)
    return False


class DeterministicReasoningModel:
    """Transparent rule-based stand-in for a future LLM reasoner.

    Args:
        force_first_action: test hook only. When set, the first decision
            is forced to the given action regardless of evidence so tests
            can exercise the wrong-action recovery path. Never used in
            normal operation.
    """

    def __init__(self, force_first_action: str | None = None) -> None:
        self._force_first_action = force_first_action
        self._forced = False

    # -- hypothesis scoring -------------------------------------------

    def evaluate_hypotheses(
        self,
        observations: dict,
        memories: list[dict],
        observation_history: list[dict] | None = None,
        failed_actions: list[str] | None = None,
    ) -> list[Hypothesis]:
        metrics = observations.get("metrics") if isinstance(observations, dict) else None
        state = observations.get("state") if isinstance(observations, dict) else None
        logs = observations.get("logs") if isinstance(observations, dict) else None
        if not isinstance(metrics, dict):
            metrics = {}
        if not isinstance(state, dict):
            state = {}
        history = observation_history or []
        failed = set(failed_actions or [])

        db_used = _num(metrics, "db_connections")
        db_limit = _num(metrics, "db_connection_limit", 100.0) or 100.0
        db_ratio = db_used / db_limit if db_limit else 0.0
        db_lat = _num(metrics, "db_latency_ms")
        five_xx = _num(metrics, "http_5xx_rate")
        cpu = _num(metrics, "cpu")
        mem = _num(metrics, "memory")
        redis_health = _str(metrics, "redis_health", "healthy")
        dep_lat = _num(metrics, "dependency_latency_ms")
        req_rate = _num(metrics, "request_rate")
        queue = _num(metrics, "queue_depth")
        disk = _num(metrics, "disk_utilization")
        deploy_version = _str(metrics, "deployment_version", "1.4.2")
        deploy_status = _str(metrics, "deployment_status", "healthy")
        p95 = _num(metrics, "p95_latency_ms")

        state_block = state if isinstance(state, dict) else {}
        deploy_block = state_block.get("deployment") if isinstance(state_block, dict) else {}
        redis_block = state_block.get("redis") if isinstance(state_block, dict) else {}
        disk_block = state_block.get("disk") if isinstance(state_block, dict) else {}
        if isinstance(deploy_block, dict):
            deploy_status = str(deploy_block.get("status", deploy_status))
            deploy_version = str(deploy_block.get("version", deploy_version))
        if isinstance(redis_block, dict):
            redis_health = str(redis_block.get("status", redis_health))

        log_text = ""
        if isinstance(logs, dict) and isinstance(logs.get("logs"), list):
            log_text = "\n".join(str(line) for line in logs["logs"][-20:])
        elif isinstance(observations.get("snapshot"), dict):
            snap = observations["snapshot"]
            if isinstance(snap, dict) and isinstance(snap.get("logs"), list):
                log_text = "\n".join(str(line) for line in snap["logs"][-20:])
        log_lower = log_text.lower()

        mem_trend_up = False
        if history:
            past = [_num(h, "memory") for h in history if isinstance(h, dict)]
            past = [v for v in past if v > 0]
            if past and mem > max(past) + 0.5:
                mem_trend_up = True
        if mem_trend_up is False and len(history) >= 1 and mem >= 84:
            # Single prior reading plus currently-high memory is weak
            # evidence, but not yet a confirmed trend.
            pass

        recent_deploy = deploy_status == "just_deployed" or deploy_version != "1.4.2"

        scored: list[Hypothesis] = []

        def finalize(
            statement: str,
            score: float,
            supporting: list[str],
            contradicting: list[str],
        ) -> None:
            if HYPOTHESIS_ACTION.get(statement) in failed:
                score -= 0.35
                contradicting = list(contradicting) + ["previous action had no effect"]
            elif _memory_recalls_action_failure(
                memories, HYPOTHESIS_ACTION.get(statement, "")
            ):
                # Historical failure is weak negative evidence: current
                # observations stay authoritative, but a recalled failure
                # must never count as support for retrying the same action.
                score -= 0.10
                contradicting = list(contradicting) + [
                    "hindsight recalls this action failing before"
                ]
            confidence = max(0.05, min(0.95, score))
            if confidence >= SUPPORTED_THRESHOLD:
                status = "supported"
            elif confidence <= REJECTED_THRESHOLD:
                status = "rejected"
            elif confidence >= 0.35:
                status = "investigating"
            else:
                status = "considered"
            scored.append(
                Hypothesis(
                    statement=statement,
                    status=status,
                    confidence=round(confidence, 2),
                    supporting=supporting,
                    contradicting=contradicting,
                )
            )

        # -- DB pool exhaustion --------------------------------------
        score, sup, con = 0.05, [], []
        if db_ratio >= 0.95:
            score += 0.40
            sup.append(f"db_connections saturated ({int(db_used)}/{int(db_limit)})")
        elif db_ratio < 0.70:
            score -= 0.30
            con.append(f"db_connections normal ({int(db_used)}/{int(db_limit)})")
        if db_lat >= 500:
            score += 0.25
            sup.append(f"db_latency very high ({db_lat:.0f}ms)")
        elif db_lat < 100:
            score -= 0.20
            con.append(f"db_latency normal ({db_lat:.0f}ms)")
        if five_xx >= 10:
            score += 0.15
            sup.append(f"5xx elevated ({five_xx}%)")
        if cpu >= 80:
            score -= 0.10
            con.append(f"cpu high ({cpu}%), suggests load rather than pool")
        if req_rate >= 300:
            score -= 0.10
            con.append(f"request rate elevated ({req_rate:.0f}), not isolated pool pressure")
        if _memory_mentions(memories, "db pool", "connection pool", "db_connection"):
            score += 0.10
            sup.append("hindsight recalls a similar DB pool incident")
        finalize(HYPOTHESIS_DB_POOL, score, sup, con)

        # -- bad deployment ------------------------------------------
        score, sup, con = 0.05, [], []
        if recent_deploy:
            score += 0.50
            sup.append(f"recent deployment ({deploy_version}, status={deploy_status})")
        else:
            score -= 0.30
            con.append("no recent deployment (v1.4.2 healthy)")
        if five_xx >= 10:
            score += 0.15
            sup.append(f"5xx elevated ({five_xx}%)")
        if db_ratio < 0.70 and db_lat < 100:
            score += 0.10
            sup.append("DB healthy, points away from DB cause")
        if cpu < 70:
            score += 0.05
            sup.append(f"cpu not unusually high ({cpu}%)")
        if _memory_mentions(memories, "deploy", "rollback", "v1.5"):
            score += 0.10
            sup.append("hindsight recalls a bad-deployment incident")
        finalize(HYPOTHESIS_BAD_DEPLOY, score, sup, con)

        # -- memory leak ---------------------------------------------
        score, sup, con = 0.05, [], []
        if mem >= 90:
            score += 0.40
            sup.append(f"memory critically high ({mem}%)")
        elif mem >= 80:
            score += 0.30
            sup.append(f"memory high ({mem}%)")
        elif mem < 75:
            score -= 0.30
            con.append(f"memory normal ({mem}%)")
        if mem_trend_up:
            score += 0.25
            sup.append("memory increasing across observations")
        if 2 <= five_xx <= 15:
            score += 0.10
            sup.append(f"moderate 5xx elevation ({five_xx}%)")
        if _memory_mentions(memories, "memory leak", "heap", "restart_service"):
            score += 0.08
            sup.append("hindsight recalls a memory-leak incident")
        finalize(HYPOTHESIS_MEM_LEAK, score, sup, con)

        # -- redis failure -------------------------------------------
        score, sup, con = 0.05, [], []
        if redis_health == "unavailable":
            score += 0.50
            sup.append("redis unavailable")
        elif redis_health == "degraded":
            score += 0.20
            sup.append("redis degraded")
        else:
            score -= 0.40
            con.append("redis healthy")
        if 80 <= db_lat <= 300:
            score += 0.10
            sup.append(f"DB latency rising ({db_lat:.0f}ms), cache fallback load")
        if db_ratio >= 0.9:
            score -= 0.05
            con.append("DB nearly saturated, less typical of pure redis failure")
        if _memory_mentions(memories, "redis", "cache"):
            score += 0.08
            sup.append("hindsight recalls a redis incident")
        finalize(HYPOTHESIS_REDIS, score, sup, con)

        # -- dependency timeout --------------------------------------
        score, sup, con = 0.05, [], []
        if dep_lat >= 2000:
            score += 0.50
            sup.append(f"dependency latency extreme ({dep_lat:.0f}ms)")
        elif dep_lat >= 500:
            score += 0.25
            sup.append(f"dependency latency high ({dep_lat:.0f}ms)")
        else:
            score -= 0.30
            con.append(f"dependency latency normal ({dep_lat:.0f}ms)")
        if p95 >= 4000 or " 504" in log_lower or "returned 504" in log_lower:
            score += 0.15
            sup.append("504 responses / extreme tail latency observed")
        if five_xx >= 15 and dep_lat >= 500:
            score += 0.10
            sup.append(f"5xx elevated with slow dependency ({five_xx}%)")
        finalize(HYPOTHESIS_DEP_TIMEOUT, score, sup, con)

        # -- traffic spike -------------------------------------------
        score, sup, con = 0.05, [], []
        if req_rate >= 1000:
            score += 0.40
            sup.append(f"request rate unusually high ({req_rate:.0f})")
        elif req_rate >= 300:
            score += 0.15
            sup.append(f"request rate elevated ({req_rate:.0f})")
        else:
            score -= 0.30
            con.append(f"request rate normal ({req_rate:.0f})")
        if cpu >= 85:
            score += 0.20
            sup.append(f"cpu high ({cpu}%)")
        elif cpu < 70:
            score -= 0.15
            con.append(f"cpu normal ({cpu}%)")
        if queue >= 200:
            score += 0.20
            sup.append(f"queue depth high ({queue:.0f})")
        elif queue < 50:
            score -= 0.10
            con.append(f"queue depth normal ({queue:.0f})")
        if _memory_mentions(memories, "traffic", "spike", "scale"):
            score += 0.08
            sup.append("hindsight recalls a traffic-spike incident")
        finalize(HYPOTHESIS_TRAFFIC, score, sup, con)

        # -- cache stampede ------------------------------------------
        score, sup, con = 0.05, [], []
        if redis_health == "degraded":
            score += 0.25
            sup.append("cache degraded")
        elif redis_health == "unavailable":
            score += 0.10
            sup.append("cache unavailable")
        else:
            score -= 0.35
            con.append("cache healthy")
        if db_used >= 90:
            score += 0.25
            sup.append(f"DB connections very high ({int(db_used)}/{int(db_limit)})")
        elif db_ratio < 0.70:
            score -= 0.20
            con.append("DB load normal")
        if db_lat >= 400:
            score += 0.20
            sup.append(f"DB latency high ({db_lat:.0f}ms)")
        if cpu >= 75:
            score += 0.15
            sup.append(f"cpu high ({cpu}%)")
        if 200 <= req_rate <= 900:
            score += 0.10
            sup.append(f"elevated request rate ({req_rate:.0f}) with degraded cache")
        if "thundering herd" in log_lower or "hit ratio" in log_lower:
            score += 0.10
            sup.append("cache-stampede signatures in logs")
        finalize(HYPOTHESIS_STAMPEDE, score, sup, con)

        # -- disk exhaustion -----------------------------------------
        score, sup, con = 0.05, [], []
        disk_full = isinstance(disk_block, dict) and disk_block.get("status") == "full"
        if disk >= 95 or disk_full:
            score += 0.55
            sup.append(f"disk utilization critical ({disk}%)")
        elif disk < 90:
            score -= 0.40
            con.append(f"disk utilization normal ({disk}%)")
        if "no space left" in log_lower:
            score += 0.15
            sup.append("disk-full errors in logs")
        finalize(HYPOTHESIS_DISK, score, sup, con)

        scored.sort(key=lambda h: (h.confidence or 0.0), reverse=True)
        return scored

    # -- step selection -----------------------------------------------

    def choose_next_step(self, state: AgentState) -> ReasoningDecision:
        if self._force_first_action and not self._forced and state.action_count == 0:
            self._forced = True
            return ReasoningDecision(
                type="act",
                action=self._force_first_action,
                reasoning=(
                    "Test hook: forced first action to exercise "
                    "wrong-action recovery; not evidence-based."
                ),
                hypothesis=None,
                confidence=0.1,
            )

        observations = state.observations or {}
        for tool in ("get_health", "get_metrics", "get_state", "get_logs"):
            if tool not in observations:
                return ReasoningDecision(
                    type="observe",
                    tool=tool,
                    reasoning=f"Baseline observation incomplete; need {tool}.",
                )

        hypotheses = self.evaluate_hypotheses(
            observations,
            state.recalled_memories,
            observation_history=state.observation_history,
            failed_actions=state.failed_actions,
        )
        candidates = [
            h
            for h in hypotheses
            if (h.confidence or 0.0) >= ACT_CONFIDENCE_THRESHOLD
            and HYPOTHESIS_ACTION.get(h.statement) not in state.failed_actions
        ]
        if candidates and state.action_count < 99:  # agent enforces MAX_ACTIONS
            best = candidates[0]
            action = HYPOTHESIS_ACTION.get(best.statement)
            if action:
                logger.info(
                    "ACTION_PROPOSED hypothesis=%s confidence=%s action=%s",
                    best.statement,
                    best.confidence,
                    action,
                )
                return ReasoningDecision(
                    type="act",
                    action=action,
                    reasoning=(
                        f"Hypothesis '{best.statement}' supported "
                        f"(confidence {best.confidence}): "
                        f"{'; '.join(best.supporting[:3]) or 'evidence converged'}."
                    ),
                    hypothesis=best.statement,
                    confidence=best.confidence,
                )

        # No confident, untried hypothesis: investigate further if budget allows.
        metrics_reads = sum(1 for t in state.tools_used if t == "get_metrics")
        best_overall = hypotheses[0] if hypotheses else None
        if (
            best_overall is not None
            and best_overall.statement == HYPOTHESIS_MEM_LEAK
            and metrics_reads < 2
        ):
            return ReasoningDecision(
                type="investigate",
                tool="get_metrics",
                reasoning=(
                    "Memory-leak hypothesis requires a second reading to "
                    "confirm an increasing trend."
                ),
                hypothesis=best_overall.statement,
                confidence=best_overall.confidence,
            )
        if "get_snapshot" not in state.tools_used:
            return ReasoningDecision(
                type="investigate",
                tool="get_snapshot",
                reasoning="No hypothesis is confident; gathering a full snapshot.",
            )
        if "get_logs" in observations and state.investigation_count < 4:
            return ReasoningDecision(
                type="investigate",
                tool="get_metrics",
                reasoning="Re-checking live metrics before concluding.",
            )
        if best_overall is not None and (best_overall.confidence or 0) >= 0.35:
            action = HYPOTHESIS_ACTION.get(best_overall.statement)
            if action and action not in state.failed_actions:
                return ReasoningDecision(
                    type="act",
                    action=action,
                    reasoning=(
                        f"Best available hypothesis '{best_overall.statement}' "
                        f"(confidence {best_overall.confidence}); acting before "
                        "investigation budget is exhausted."
                    ),
                    hypothesis=best_overall.statement,
                    confidence=best_overall.confidence,
                )
        return ReasoningDecision(
            type="escalate",
            reasoning="No supported hypothesis remains; escalating to a human.",
        )

"""Evaluation runner: controlled scenarios around the unmodified agent.

Evaluator privileges (reset / inject / run / collect) never cross into the
agent: the agent sees only tool results built from observable simulator
state, plus Hindsight memories containing legitimate prior experiences.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.evaluation.models import (
    ComparisonReport,
    EvaluationReport,
    EvaluationResult,
    LearningExperimentResult,
    MetricSlice,
    MisleadingMemoryResult,
    ScenarioComparison,
)
from app.evaluation.scenarios import (
    DB_RELEVANT_SCENARIO,
    MISLEADING_CURRENT_SCENARIO,
    MISLEADING_HISTORY_SCENARIO,
    SCENARIOS,
    new_scenario_incident,
)
from app.models.incident import Incident
from app.services.agent import IncidentResponseAgent, InMemoryHindsight
from app.services.agent_tools import AgentTools
from app.services.payment_simulator import FAULTS, PaymentSimulator
from app.services.reasoning_model import DeterministicReasoningModel

logger = logging.getLogger(__name__)

_SUPPORTED_STATUSES = {"supported", "selected"}

REASONING_CHOICES: tuple[str, ...] = ("deterministic", "llm")


def build_reasoning_model(choice: str) -> tuple[object, str, str | None]:
    """Create the reasoning backend for an evaluation run.

    Returns (model, model_name, reasoning_effort). 'llm' requires
    GROQ_API_KEY and raises instead of falling back — a silent fallback
    would invalidate evaluation results.
    """
    from app.config.settings import get_settings

    normalized = (choice or "deterministic").strip().lower()
    if normalized == "deterministic":
        return DeterministicReasoningModel(), "deterministic", None
    if normalized == "llm":
        from app.services.llm_reasoning_model import LLMReasoningModel

        settings = get_settings()
        return (
            LLMReasoningModel.from_settings(settings),
            settings.groq_model,
            settings.groq_reasoning_effort,
        )
    raise ValueError(
        f"Unknown reasoning model: {choice!r} (expected one of {REASONING_CHOICES})."
    )


def _llm_metrics_of(model: object) -> dict[str, object]:
    metrics = getattr(model, "metrics", None)
    if isinstance(metrics, dict):
        return metrics
    return {
        "llm_calls": 0,
        "llm_latency_ms": 0.0,
        "llm_errors": 0,
        "llm_retries": 0,
    }


class InstrumentedHindsight:
    """Counting decorator over ``InMemoryHindsight``.

    Same interface the agent expects, plus per-run recall/retention
    counters. This is the smallest instrumentation that lets the evaluator
    measure memory use without changing agent behavior.
    """

    def __init__(self) -> None:
        self._inner = InMemoryHindsight()
        self._incidents: list[Incident] = []
        self.initial_size = 0
        self.recall_calls = 0
        self.recalled_total = 0
        self.recalled_ids: list[str] = []
        self.retained_ids: list[str] = []

    async def seed(self, incidents: list[Incident]) -> None:
        """Load legitimate prior experiences (no current-scenario truth)."""
        for incident in incidents:
            await self.retain_incident(incident)
        self.initial_size = self._inner.retained_count

    async def retain_incident(self, incident: Incident) -> dict[str, object]:
        result = await self._inner.retain_incident(incident)
        self._incidents.append(incident)
        self.retained_ids.append(incident.incident_id)
        return result

    async def recall_incidents(
        self, query: str, max_tokens: int = 4096
    ) -> list[dict[str, object]]:
        memories = await self._inner.recall_incidents(query, max_tokens)
        self.recall_calls += 1
        self.recalled_total += len(memories)
        for memory in memories:
            metadata = memory.get("metadata")
            if isinstance(metadata, dict):
                memory_id = metadata.get("incident_id")
                if isinstance(memory_id, str) and memory_id not in self.recalled_ids:
                    self.recalled_ids.append(memory_id)
        return memories

    @property
    def retained_count(self) -> int:
        return self._inner.retained_count

    @property
    def seeds(self) -> list[Incident]:
        return list(self._incidents)


def _wrong_action_count(incident: Incident) -> int:
    """Count actions with no meaningful improvement, from agent records.

    Primary source is the agent's own ``Learning.failed_actions``. The
    result-text scan is only a fallback for incidents without learning.
    Ground truth is never consulted.
    """
    if incident.learning is not None:
        return len(incident.learning.failed_actions)
    count = 0
    for action in incident.actions:
        if action.result and "no significant change" in action.result.lower():
            count += 1
    return count


def _final_action(incident: Incident) -> str | None:
    if incident.learning is not None and incident.learning.successful_actions:
        return incident.learning.successful_actions[-1]
    return None


def _collect_result(
    scenario: str,
    mode: str,
    incident: Incident,
    hindsight: InstrumentedHindsight,
    duration_seconds: float,
    empty_at_start: bool,
    llm_metrics: dict[str, object] | None = None,
    model_name: str | None = None,
    reasoning_effort: str | None = None,
) -> EvaluationResult:
    learning = incident.learning
    verification = incident.verification
    supported = sum(1 for h in incident.hypotheses if h.status in _SUPPORTED_STATUSES)
    rejected = sum(1 for h in incident.hypotheses if h.status == "rejected")
    outcome = learning.outcome if learning else None
    llm_metrics = llm_metrics or {}
    return EvaluationResult(
        scenario=scenario,
        mode=mode,
        resolved=outcome == "resolved",
        outcome=outcome,
        investigation_steps=len(incident.investigation),
        actions_count=len(incident.actions),
        wrong_actions=_wrong_action_count(incident),
        actions_taken=[a.action for a in incident.actions],
        hypotheses_considered=len(incident.hypotheses),
        hypotheses_supported=supported,
        hypotheses_rejected=rejected,
        final_action=_final_action(incident),
        verification_improved=verification.improved if verification else None,
        hindsight_memories_recalled=hindsight.recalled_total,
        recalled_memory_ids=list(hindsight.recalled_ids),
        hindsight_retained=incident.incident_id in hindsight.retained_ids,
        hindsight_empty_at_start=empty_at_start,
        llm_calls=int(llm_metrics.get("llm_calls", 0) or 0),
        llm_latency_ms=float(llm_metrics.get("llm_latency_ms", 0.0) or 0.0),
        llm_errors=int(llm_metrics.get("llm_errors", 0) or 0),
        llm_retries=int(llm_metrics.get("llm_retries", 0) or 0),
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        duration_seconds=round(duration_seconds, 3),
        lesson=learning.lesson if learning else None,
        incident=incident.model_dump(mode="json"),
    )


async def evaluate_scenario(
    scenario: str,
    mode: str,
    hindsight: InstrumentedHindsight,
    simulator: PaymentSimulator | None = None,
    seq: int = 0,
    reasoning: str = "deterministic",
) -> EvaluationResult:
    """Reset -> inject -> run agent -> collect. Simulator left clean."""
    if scenario not in FAULTS:
        raise ValueError(f"Unknown scenario: {scenario}")
    simulator = simulator or PaymentSimulator()
    empty_at_start = hindsight.retained_count == 0
    reasoning_model, model_name, effort = build_reasoning_model(reasoning)

    simulator.reset()
    simulator.inject_fault(scenario)
    incident = new_scenario_incident(mode, seq)
    agent = IncidentResponseAgent(
        reasoning_model=reasoning_model,  # type: ignore[arg-type]
        tools=AgentTools(simulator),
        hindsight=hindsight,
    )
    logger.info(
        "EVAL_START scenario=%s mode=%s reasoning=%s", scenario, mode, reasoning
    )
    started = time.perf_counter()
    error: str | None = None
    try:
        finished = await agent.run(incident)
    except Exception as exc:
        # Reasoning failures (e.g. LLM API errors) are recorded as an
        # explicit error outcome — visible in the report, never masked as
        # a fabricated success. Anything else is a harness/agent bug.
        from app.services.llm_reasoning_model import LLMReasoningError

        if not isinstance(exc, LLMReasoningError):
            raise
        error = f"{type(exc).__name__}: {exc}"
        finished = incident
        logger.warning(
            "EVAL_ERROR scenario=%s mode=%s reasoning=%s error=%s",
            scenario,
            mode,
            reasoning,
            error,
        )
    finally:
        simulator.reset()
    duration = time.perf_counter() - started
    result = _collect_result(
        scenario,
        mode,
        finished,
        hindsight,
        duration,
        empty_at_start,
        _llm_metrics_of(reasoning_model),
        model_name,
        effort,
    )
    if error is not None:
        result.outcome = "error"
        result.resolved = False
        result.lesson = f"Evaluation recorded a reasoning failure: {error}"
    logger.info(
        "EVAL_DONE scenario=%s mode=%s resolved=%s steps=%d actions=%d",
        scenario,
        mode,
        result.resolved,
        result.investigation_steps,
        result.actions_count,
    )
    return result


def _totals(results: list[EvaluationResult]) -> dict[str, float]:
    count = len(results)
    if count == 0:
        return {}
    return {
        "total_scenarios": float(count),
        "resolved_scenarios": float(sum(1 for r in results if r.resolved)),
        "average_investigation_steps": round(
            sum(r.investigation_steps for r in results) / count, 2
        ),
        "average_actions": round(
            sum(r.actions_count for r in results) / count, 2
        ),
        "total_wrong_actions": float(sum(r.wrong_actions for r in results)),
        "average_recalled_memories": round(
            sum(r.hindsight_memories_recalled for r in results) / count, 2
        ),
        "total_llm_calls": float(sum(r.llm_calls for r in results)),
        "total_llm_errors": float(sum(r.llm_errors for r in results)),
        "total_llm_retries": float(sum(r.llm_retries for r in results)),
        "average_llm_latency_ms": round(
            sum(r.llm_latency_ms for r in results) / count, 1
        ),
    }


async def run_cold_evaluation(
    scenarios: list[str] | None = None,
    simulator: PaymentSimulator | None = None,
    reasoning: str = "deterministic",
) -> EvaluationReport:
    """Every scenario with empty Hindsight (isolated baseline)."""
    scenarios = scenarios or SCENARIOS
    simulator = simulator or PaymentSimulator()
    results: list[EvaluationResult] = []
    for seq, scenario in enumerate(scenarios):
        memory = InstrumentedHindsight()
        results.append(
            await evaluate_scenario(scenario, "cold", memory, simulator, seq, reasoning)
        )
    return EvaluationReport(
        mode="cold",
        reasoning_model=reasoning,
        generated_at=datetime.now(timezone.utc),
        results=results,
        totals=_totals(results),
    )


async def run_experienced_evaluation(
    seed_incidents: list[Incident],
    scenarios: list[str] | None = None,
    simulator: PaymentSimulator | None = None,
    reasoning: str = "deterministic",
) -> EvaluationReport:
    """Every scenario with legitimate prior experiences available.

    Each scenario receives an independent copy of the seed store, so runs
    stay isolated while sharing the same prior experience.
    """
    scenarios = scenarios or SCENARIOS
    simulator = simulator or PaymentSimulator()
    results: list[EvaluationResult] = []
    for seq, scenario in enumerate(scenarios):
        memory = InstrumentedHindsight()
        await memory.seed(seed_incidents)
        results.append(
            await evaluate_scenario(
                scenario, "experienced", memory, simulator, seq, reasoning
            )
        )
    return EvaluationReport(
        mode="experienced",
        reasoning_model=reasoning,
        generated_at=datetime.now(timezone.utc),
        results=results,
        totals=_totals(results),
    )


def seed_incidents_from_report(report: EvaluationReport) -> list[Incident]:
    """Rebuild retained incidents from a prior report for experienced runs."""
    incidents: list[Incident] = []
    for result in report.results:
        if result.hindsight_retained:
            incidents.append(Incident.model_validate(result.incident))
    return incidents


def _to_slice(result: EvaluationResult) -> MetricSlice:
    return MetricSlice(
        resolved=result.resolved,
        investigation_steps=result.investigation_steps,
        actions_count=result.actions_count,
        wrong_actions=result.wrong_actions,
        final_action=result.final_action,
        hindsight_memories_recalled=result.hindsight_memories_recalled,
    )


def compare_reports(
    cold: EvaluationReport, experienced: EvaluationReport
) -> ComparisonReport:
    """Side-by-side observed measurements. No subjective better/worse score."""
    exp_by_scenario = {r.scenario: r for r in experienced.results}
    comparisons = [
        ScenarioComparison(
            scenario=result.scenario,
            cold=_to_slice(result),
            experienced=_to_slice(exp_by_scenario[result.scenario])
            if result.scenario in exp_by_scenario
            else MetricSlice(),
        )
        for result in cold.results
    ]
    return ComparisonReport(
        generated_at=datetime.now(timezone.utc),
        comparisons=comparisons,
        cold_totals=_totals(cold.results),
        experienced_totals=_totals(experienced.results),
    )


def _hypothesis_statuses(incident: Incident) -> dict[str, str]:
    return {h.statement: h.status for h in incident.hypotheses}


async def run_learning_experiment(
    simulator: PaymentSimulator | None = None,
    reasoning: str = "deterministic",
) -> LearningExperimentResult:
    """Stage 1 resolves one fault; stage 2 reuses that experience (§16)."""
    simulator = simulator or PaymentSimulator()

    stage1_memory = InstrumentedHindsight()
    stage1 = await evaluate_scenario(
        MISLEADING_HISTORY_SCENARIO,
        "learning-stage1",
        stage1_memory,
        simulator,
        0,
        reasoning,
    )
    history = [Incident.model_validate(stage1.incident)]

    stage2_memory = InstrumentedHindsight()
    await stage2_memory.seed(history)
    stage2 = await evaluate_scenario(
        DB_RELEVANT_SCENARIO, "learning-stage2", stage2_memory, simulator, 1, reasoning
    )
    stage2_incident = Incident.model_validate(stage2.incident)
    return LearningExperimentResult(
        stage1=stage1,
        stage2=stage2,
        stage2_recalled_memory_ids=list(stage2_memory.recalled_ids),
        stage2_hypothesis_statuses=_hypothesis_statuses(stage2_incident),
    )


async def run_misleading_memory_experiment(
    simulator: PaymentSimulator | None = None,
    reasoning: str = "deterministic",
) -> MisleadingMemoryResult:
    """History suggests DB failure; current evidence says bad deployment (§17)."""
    simulator = simulator or PaymentSimulator()

    history_memory = InstrumentedHindsight()
    history_result = await evaluate_scenario(
        MISLEADING_HISTORY_SCENARIO,
        "misleading-history",
        history_memory,
        simulator,
        0,
        reasoning,
    )
    history = [Incident.model_validate(history_result.incident)]

    current_memory = InstrumentedHindsight()
    await current_memory.seed(history)
    current = await evaluate_scenario(
        MISLEADING_CURRENT_SCENARIO,
        "misleading-current",
        current_memory,
        simulator,
        1,
        reasoning,
    )
    current_incident = Incident.model_validate(current.incident)
    statuses = _hypothesis_statuses(current_incident)
    selected = next(
        (h.statement for h in current_incident.hypotheses if h.status == "selected"),
        next(
            (
                h.statement
                for h in current_incident.hypotheses
                if h.status == "supported"
            ),
            None,
        ),
    )
    return MisleadingMemoryResult(
        history_scenario=MISLEADING_HISTORY_SCENARIO,
        current_scenario=MISLEADING_CURRENT_SCENARIO,
        recalled_memory_ids=list(current_memory.recalled_ids),
        db_hypothesis_status=statuses.get("DB pool exhaustion"),
        selected_hypothesis=selected,
        final_action=current.final_action,
        resolved=current.resolved,
        investigation_steps=current.investigation_steps,
        result=current,
    )


def render_text_report(
    cold: EvaluationReport,
    experienced: EvaluationReport,
    comparison: ComparisonReport,
) -> str:
    """Human-readable summary matching the §13 example shape."""
    lines = ["OPSYN Evaluation", "================", ""]
    reasoning_label = cold.reasoning_model or "deterministic"
    lines.append(f"Reasoning: {reasoning_label}")
    model_names = {r.model_name for r in cold.results if r.model_name}
    if model_names:
        lines.append(f"Model: {sorted(model_names)[0]}")
    lines.append("")
    for entry in comparison.comparisons:
        lines.append(f"Scenario: {entry.scenario}")
        lines.append("")
        lines.append("COLD")
        lines.append("-----")
        lines.append(f"Resolved: {str(entry.cold.resolved).lower()}")
        lines.append(f"Steps: {entry.cold.investigation_steps}")
        lines.append(f"Actions: {entry.cold.actions_count}")
        lines.append(f"Wrong actions: {entry.cold.wrong_actions}")
        lines.append(f"Memories recalled: {entry.cold.hindsight_memories_recalled}")
        lines.append(f"Final action: {entry.cold.final_action}")
        cold_llm = next(
            (r for r in cold.results if r.scenario == entry.scenario), None
        )
        if cold_llm is not None and cold_llm.llm_calls:
            lines.append(
                f"LLM calls: {cold_llm.llm_calls} "
                f"latency_ms={cold_llm.llm_latency_ms:.0f} "
                f"errors={cold_llm.llm_errors} retries={cold_llm.llm_retries}"
            )
        lines.append("")
        lines.append("EXPERIENCED")
        lines.append("-----------")
        lines.append(f"Resolved: {str(entry.experienced.resolved).lower()}")
        lines.append(f"Steps: {entry.experienced.investigation_steps}")
        lines.append(f"Actions: {entry.experienced.actions_count}")
        lines.append(f"Wrong actions: {entry.experienced.wrong_actions}")
        lines.append(
            f"Memories recalled: {entry.experienced.hindsight_memories_recalled}"
        )
        lines.append(f"Final action: {entry.experienced.final_action}")
        exp_llm = next(
            (r for r in experienced.results if r.scenario == entry.scenario), None
        )
        if exp_llm is not None and exp_llm.llm_calls:
            lines.append(
                f"LLM calls: {exp_llm.llm_calls} "
                f"latency_ms={exp_llm.llm_latency_ms:.0f} "
                f"errors={exp_llm.llm_errors} retries={exp_llm.llm_retries}"
            )
        lines.append("")
    lines.append("Aggregate Summary")
    lines.append("-----------------")
    header = f"{'Scenario':<22}{'Cold':<64}{'Experienced':<64}"
    lines.append(header)
    for entry in comparison.comparisons:
        cold_cell = (
            f"resolved={entry.cold.resolved} steps={entry.cold.investigation_steps} "
            f"actions={entry.cold.actions_count} wrong={entry.cold.wrong_actions} "
            f"recalled={entry.cold.hindsight_memories_recalled}"
        )
        exp_cell = (
            f"resolved={entry.experienced.resolved} "
            f"steps={entry.experienced.investigation_steps} "
            f"actions={entry.experienced.actions_count} "
            f"wrong={entry.experienced.wrong_actions} "
            f"recalled={entry.experienced.hindsight_memories_recalled}"
        )
        lines.append(f"{entry.scenario:<22}{cold_cell:<64}{exp_cell:<64}")
    lines.append("")
    for label, totals in (
        ("Cold totals", comparison.cold_totals),
        ("Experienced totals", comparison.experienced_totals),
    ):
        lines.append(f"{label}: " + ", ".join(f"{k}={v}" for k, v in totals.items()))
    lines.append("")
    lines.append(f"Cold scenarios: {len(cold.results)} / {len(SCENARIOS)}")
    lines.append(
        f"Experienced scenarios: {len(experienced.results)} / {len(SCENARIOS)}"
    )
    return "\n".join(lines)


def save_report(report: object, path: str | Path) -> Path:
    """Persist any report model as machine-readable JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(report, "model_dump_json"):
        target.write_text(
            report.model_dump_json(indent=2),  # type: ignore[union-attr]
            encoding="utf-8",
        )
    else:
        target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return target

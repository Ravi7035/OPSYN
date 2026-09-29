"""Tests for the OPSYN evaluation harness (deterministic, no LLM).

The evaluator controls the simulator (reset/inject); the agent under test
only ever sees observable tool results plus legitimate prior experiences.
"""

import json

import pytest

from app.evaluation.models import EvaluationResult
from app.evaluation.runner import (
    InstrumentedHindsight,
    compare_reports,
    evaluate_scenario,
    render_text_report,
    run_cold_evaluation,
    run_experienced_evaluation,
    run_learning_experiment,
    run_misleading_memory_experiment,
    save_report,
    seed_incidents_from_report,
)
from app.evaluation.scenarios import SCENARIOS
from app.services.payment_simulator import FAULTS, PaymentSimulator

REQUIRED_FIELDS = [
    "scenario",
    "mode",
    "resolved",
    "outcome",
    "investigation_steps",
    "actions_count",
    "wrong_actions",
    "actions_taken",
    "hypotheses_considered",
    "hypotheses_supported",
    "hypotheses_rejected",
    "final_action",
    "verification_improved",
    "hindsight_memories_recalled",
    "recalled_memory_ids",
    "hindsight_retained",
    "duration_seconds",
    "lesson",
    "incident",
]

SECRET_STRINGS = ["active_fault", "expected_action"] + list(FAULTS)


def _metric_fingerprint(result: EvaluationResult) -> dict:
    return {
        "scenario": result.scenario,
        "resolved": result.resolved,
        "outcome": result.outcome,
        "investigation_steps": result.investigation_steps,
        "actions_count": result.actions_count,
        "wrong_actions": result.wrong_actions,
        "actions_taken": result.actions_taken,
        "hypotheses_considered": result.hypotheses_considered,
        "hypotheses_supported": result.hypotheses_supported,
        "hypotheses_rejected": result.hypotheses_rejected,
        "final_action": result.final_action,
        "verification_improved": result.verification_improved,
        "hindsight_memories_recalled": result.hindsight_memories_recalled,
        "hindsight_retained": result.hindsight_retained,
    }


# -- Test 1: all scenarios execute -------------------------------------------


@pytest.mark.asyncio
async def test_all_scenarios_execute() -> None:
    report = await run_cold_evaluation()
    assert {r.scenario for r in report.results} == set(SCENARIOS) == set(FAULTS)
    assert len(report.results) == 8
    assert report.totals["total_scenarios"] == 8


# -- Test 2: scenario isolation ------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_isolation() -> None:
    simulator = PaymentSimulator()
    first = await evaluate_scenario(
        "db_pool_exhaustion", "cold", InstrumentedHindsight(), simulator, 0
    )
    second = await evaluate_scenario(
        "bad_deployment", "cold", InstrumentedHindsight(), simulator, 1
    )
    assert first.resolved and second.resolved
    # Fresh memory per scenario: nothing carries over.
    assert second.hindsight_memories_recalled == 0
    assert second.hindsight_empty_at_start is True
    # Simulator left clean after each run.
    assert simulator.get_health()["status"] == "healthy"
    assert second.final_action == "rollback_deployment"
    assert first.final_action == "clear_db_connections"


# -- Test 3: result structure ---------------------------------------------------


@pytest.mark.asyncio
async def test_result_structure() -> None:
    report = await run_cold_evaluation(scenarios=["redis_failure"])
    result = report.results[0]
    blob = json.dumps(result.model_dump(mode="json"), default=str)
    for field_name in REQUIRED_FIELDS:
        assert field_name in blob, field_name
    # Full agent trace preserved, not just resolved=true.
    trace = result.incident
    for section in ("hypotheses", "investigation", "actions", "verification", "learning"):
        assert section in trace, section
    assert trace["hypotheses"], "hypotheses must be recorded"
    assert trace["investigation"], "investigation must be recorded"


# -- Test 4: cold mode starts empty ----------------------------------------------


@pytest.mark.asyncio
async def test_cold_mode_starts_empty() -> None:
    report = await run_cold_evaluation()
    assert report.mode == "cold"
    for result in report.results:
        assert result.hindsight_empty_at_start is True
        assert result.hindsight_memories_recalled == 0
        assert result.recalled_memory_ids == []


# -- Test 5: experienced mode sees prior experience ---------------------------------


@pytest.mark.asyncio
async def test_experienced_mode_has_prior_experience() -> None:
    cold = await run_cold_evaluation()
    seeds = seed_incidents_from_report(cold)
    assert len(seeds) == len(cold.results)
    # Seeds are legitimate experiences: no fault identifiers inside.
    for seed in seeds:
        assert seed.fault_type is None
        blob = json.dumps(seed.model_dump(mode="json"), default=str)
        for secret in SECRET_STRINGS:
            assert secret not in blob, secret
    experienced = await run_experienced_evaluation(seeds)
    assert experienced.mode == "experienced"
    assert all(r.hindsight_empty_at_start is False for r in experienced.results)
    total_recalled = sum(r.hindsight_memories_recalled for r in experienced.results)
    assert total_recalled > 0


# -- Test 6: retention ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_retention_recorded() -> None:
    report = await run_cold_evaluation()
    for result in report.results:
        if result.resolved:
            assert result.hindsight_retained is True, result.scenario


# -- Test 7: memory recall reporting ----------------------------------------------------


@pytest.mark.asyncio
async def test_memory_recall_reported() -> None:
    cold = await run_cold_evaluation()
    experienced = await run_experienced_evaluation(seed_incidents_from_report(cold))
    recalled_any = [r for r in experienced.results if r.recalled_memory_ids]
    assert recalled_any, "experienced runs must report recalled memory ids"
    for result in recalled_any:
        assert result.hindsight_memories_recalled == len(result.recalled_memory_ids)


# -- Test 8: misleading memory is rejected -------------------------------------------------


@pytest.mark.asyncio
async def test_misleading_memory_rejected() -> None:
    outcome = await run_misleading_memory_experiment()
    assert outcome.history_scenario == "db_pool_exhaustion"
    assert outcome.current_scenario == "bad_deployment"
    assert outcome.recalled_memory_ids, "history must actually be recalled"
    assert outcome.db_hypothesis_status == "rejected"
    assert outcome.final_action == "rollback_deployment"
    assert outcome.resolved is True


# -- Test 9: determinism ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_determinism() -> None:
    first = await evaluate_scenario(
        "traffic_spike", "cold", InstrumentedHindsight(), PaymentSimulator(), 0
    )
    second = await evaluate_scenario(
        "traffic_spike", "cold", InstrumentedHindsight(), PaymentSimulator(), 0
    )
    assert _metric_fingerprint(first) == _metric_fingerprint(second)


# -- Comparison + learning experiment -----------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_vs_experienced_comparison() -> None:
    cold = await run_cold_evaluation()
    experienced = await run_experienced_evaluation(seed_incidents_from_report(cold))
    comparison = compare_reports(cold, experienced)
    assert {c.scenario for c in comparison.comparisons} == set(SCENARIOS)
    for entry in comparison.comparisons:
        assert entry.cold.final_action is not None
        assert entry.experienced.final_action is not None
    assert comparison.cold_totals["total_scenarios"] == 8
    assert comparison.experienced_totals["total_scenarios"] == 8
    text = render_text_report(cold, experienced, comparison)
    for scenario in SCENARIOS:
        assert scenario in text
    assert "Aggregate Summary" in text


@pytest.mark.asyncio
async def test_learning_experiment_reuses_experience() -> None:
    outcome = await run_learning_experiment()
    assert outcome.stage1.resolved is True
    assert outcome.stage1.scenario == "db_pool_exhaustion"
    assert outcome.stage2.scenario == "cache_stampede"
    assert outcome.stage2_recalled_memory_ids, "stage 2 must recall stage 1"
    assert outcome.stage2.hindsight_memories_recalled > 0
    assert outcome.stage2.resolved is True


def test_save_report_writes_json(tmp_path) -> None:
    from app.evaluation.models import EvaluationReport

    target = save_report(EvaluationReport(mode="cold"), tmp_path / "r.json")
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "cold"

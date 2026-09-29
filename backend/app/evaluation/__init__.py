"""OPSYN evaluation harness: models, scenarios, runner, CLI.

Measures the deterministic incident-response agent without modifying it:

    Fault Scenario -> Reset -> Inject -> Run Agent -> Collect -> Report
"""

from app.evaluation.models import (
    ComparisonReport,
    EvaluationReport,
    EvaluationResult,
    LearningExperimentResult,
    MetricSlice,
    MisleadingMemoryResult,
    ScenarioComparison,
)
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
)
from app.evaluation.scenarios import SCENARIOS, new_scenario_incident

__all__ = [
    "ComparisonReport",
    "EvaluationReport",
    "EvaluationResult",
    "InstrumentedHindsight",
    "LearningExperimentResult",
    "MetricSlice",
    "MisleadingMemoryResult",
    "SCENARIOS",
    "ScenarioComparison",
    "compare_reports",
    "evaluate_scenario",
    "new_scenario_incident",
    "render_text_report",
    "run_cold_evaluation",
    "run_experienced_evaluation",
    "run_learning_experiment",
    "run_misleading_memory_experiment",
    "save_report",
]

"""Structured evaluation models.

The evaluator reads measurements from the agent's own structured output
(``Incident``: hypotheses / investigation / actions / verification /
learning). Ground truth (which fault was injected) is used only to set
up the scenario, never to grade the agent's internal reasoning.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class EvaluationResult(BaseModel):
    """One scenario run. ``incident`` preserves the full agent trace."""

    model_config = ConfigDict(extra="ignore")

    scenario: str = Field(description="Injected fault name (evaluator ground truth)")
    mode: str = Field(description="'cold', 'experienced', or experiment label")
    resolved: bool = False
    outcome: str | None = None

    investigation_steps: int = 0
    actions_count: int = 0
    wrong_actions: int = 0
    actions_taken: list[str] = Field(default_factory=list)

    hypotheses_considered: int = 0
    hypotheses_supported: int = 0
    hypotheses_rejected: int = 0

    final_action: str | None = None
    verification_improved: bool | None = None

    hindsight_memories_recalled: int = 0
    recalled_memory_ids: list[str] = Field(default_factory=list)
    hindsight_retained: bool = False
    hindsight_empty_at_start: bool = False

    llm_calls: int = 0
    llm_latency_ms: float = 0.0
    llm_errors: int = 0
    llm_retries: int = 0
    model_name: str | None = None
    reasoning_effort: str | None = None

    duration_seconds: float | None = None
    lesson: str | None = None

    incident: dict = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    """All scenario results for one evaluation mode."""

    model_config = ConfigDict(extra="ignore")

    mode: str = "cold"
    reasoning_model: str = "deterministic"
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    results: list[EvaluationResult] = Field(default_factory=list)
    totals: dict[str, float] = Field(default_factory=dict)


class MetricSlice(BaseModel):
    """One side of a cold-vs-experienced comparison (observed only)."""

    model_config = ConfigDict(extra="ignore")

    resolved: bool = False
    investigation_steps: int = 0
    actions_count: int = 0
    wrong_actions: int = 0
    final_action: str | None = None
    hindsight_memories_recalled: int = 0


class ScenarioComparison(BaseModel):
    """Cold vs experienced measurements for a single scenario."""

    model_config = ConfigDict(extra="ignore")

    scenario: str = ""
    cold: MetricSlice = Field(default_factory=MetricSlice)
    experienced: MetricSlice = Field(default_factory=MetricSlice)


class ComparisonReport(BaseModel):
    """Per-scenario comparison plus aggregate totals (no subjective score)."""

    model_config = ConfigDict(extra="ignore")

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    comparisons: list[ScenarioComparison] = Field(default_factory=list)
    cold_totals: dict[str, float] = Field(default_factory=dict)
    experienced_totals: dict[str, float] = Field(default_factory=dict)


class LearningExperimentResult(BaseModel):
    """Two-stage cross-incident learning demonstration (§16)."""

    model_config = ConfigDict(extra="ignore")

    stage1: EvaluationResult
    stage2: EvaluationResult
    stage2_recalled_memory_ids: list[str] = Field(default_factory=list)
    stage2_hypothesis_statuses: dict[str, str] = Field(default_factory=dict)


class MisleadingMemoryResult(BaseModel):
    """Fallible-memory demonstration: history suggests X, evidence says Y (§17)."""

    model_config = ConfigDict(extra="ignore")

    history_scenario: str = ""
    current_scenario: str = ""
    recalled_memory_ids: list[str] = Field(default_factory=list)
    db_hypothesis_status: str | None = None
    selected_hypothesis: str | None = None
    final_action: str | None = None
    resolved: bool = False
    investigation_steps: int = 0
    result: EvaluationResult | None = None

"""Pydantic models for the future incident system.

Kept extensible: the simulator and agent layers will reuse and extend
these models, so unknown future fields are allowed.

The structured section (MetricSummary … Learning) supports the OPSYN
learning loop (Observe → Recall → Hypothesize → Investigate → Act →
Verify → Learn) for both historical RCAEval records and future
simulator experiences. All structured fields are optional: legacy
callers using only the original flat fields keep working unchanged.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    P1_CRITICAL = "P1"
    P2_HIGH = "P2"
    P3_MEDIUM = "P3"
    P4_LOW = "P4"


class IncidentSource(str, Enum):
    RCAEVAL = "rcaeval"
    SIMULATOR = "simulator"
    PRODUCTION = "production"


class MetricSummary(BaseModel):
    """Pre/post summary for one metric series (arbitrary metric names)."""

    model_config = ConfigDict(extra="ignore")

    pre_mean: float | None = Field(default=None)
    post_mean: float | None = Field(default=None)
    post_max: float | None = Field(default=None)
    delta: float | None = Field(default=None)


class EvidenceItem(BaseModel):
    """A single OBSERVED fact — never an agent conclusion."""

    model_config = ConfigDict(extra="ignore")

    signal: str = Field(description="Observed signal name, e.g. db_connections")
    value: str | float | bool | None = Field(default=None)
    observed_at: datetime | None = Field(default=None)
    provenance: str = Field(default="observed")
    stance: str = Field(default="neutral")
    refutes_memory: str | None = Field(default=None)


class Hypothesis(BaseModel):
    """An agent conclusion kept separate from observed evidence."""

    model_config = ConfigDict(extra="ignore")

    statement: str = Field(description="The hypothesized explanation")
    status: str = Field(default="considered")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)


class InvestigationStep(BaseModel):
    """One observation/tool use during investigation."""

    model_config = ConfigDict(extra="ignore")

    step_id: str = Field(description="Unique step identifier")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    tool: str = Field(description="Observation or tool used")
    target: str | None = Field(default=None)
    result_summary: str = Field(default="")
    result_refs: list[str] = Field(default_factory=list)


class AgentAction(BaseModel):
    """A proposed or executed remediation action."""

    model_config = ConfigDict(extra="ignore")

    action_id: str = Field(description="Unique action identifier")
    action: str = Field(description="Action name, e.g. rollback_deployment")
    target: str | None = Field(default=None)
    parameters: dict[str, str | float] = Field(default_factory=dict)
    status: str = Field(default="proposed")
    executed_at: datetime | None = Field(default=None)
    result: str | None = Field(default=None)


class Verification(BaseModel):
    """Before/after comparison verifying whether an action helped."""

    model_config = ConfigDict(extra="ignore")

    metrics_before: dict[str, float] = Field(default_factory=dict)
    metrics_after: dict[str, float] = Field(default_factory=dict)
    improved: bool | None = Field(default=None)
    status: str = Field(default="pending")


class Learning(BaseModel):
    """Incident outcome. Failed/unresolved episodes stay representable."""

    model_config = ConfigDict(extra="ignore")

    outcome: str | None = Field(default=None)
    successful_actions: list[str] = Field(default_factory=list)
    failed_actions: list[str] = Field(default_factory=list)
    lesson: str | None = Field(default=None)
    suitable_for_hindsight: bool = Field(default=False)


class Incident(BaseModel):
    """A single production incident experience."""

    model_config = ConfigDict(extra="allow")

    incident_id: str = Field(description="Unique incident identifier")
    service: str = Field(description="Affected service, e.g. payment-api")
    environment: str = Field(default="production")
    severity: Severity = Field(default=Severity.P2_HIGH)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the incident started",
    )
    symptoms: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    metrics: dict[str, str] = Field(default_factory=dict)
    root_cause: str | None = Field(default=None)
    actions_taken: list[str] = Field(default_factory=list)
    resolution: str | None = Field(default=None)
    resolution_time_minutes: float | None = Field(default=None)
    customer_impact: str | None = Field(default=None)
    lesson: str | None = Field(default=None)

    # Structured OPSYN extensions (all optional; §3 of INCIDENT_SCHEMA_DESIGN.md).
    source: IncidentSource | None = Field(default=None)
    source_case_id: str | None = Field(default=None)
    fault_type: str | None = Field(default=None)
    time_window_start: datetime | None = Field(default=None)
    time_window_end: datetime | None = Field(default=None)
    metric_summaries: dict[str, MetricSummary] = Field(default_factory=dict)
    trace_summary: dict | None = Field(default=None)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    investigation: list[InvestigationStep] = Field(default_factory=list)
    actions: list[AgentAction] = Field(default_factory=list)
    verification: Verification | None = Field(default=None)
    learning: Learning | None = Field(default=None)

    def to_memory_text(self) -> str:
        """Render the incident as human-readable text for retain().

        Legacy lines first (unchanged), then structured sections in fixed
        order. Sections with no data are omitted; nothing is invented.
        """
        lines = [
            f"Incident {self.incident_id}: {self.service} "
            f"({self.environment}, {self.severity.value}) experienced an issue.",
            f"Symptoms: {'; '.join(self.symptoms) or 'n/a'}",
            f"Metrics: {'; '.join(f'{k}={v}' for k, v in self.metrics.items()) or 'n/a'}",
            f"Logs: {'; '.join(self.logs) or 'n/a'}",
            f"Root cause: {self.root_cause or 'unknown'}",
            f"Actions taken: {'; '.join(self.actions_taken) or 'none recorded'}",
            f"Resolution: {self.resolution or 'unresolved'}",
        ]
        if self.resolution_time_minutes is not None:
            lines.append(f"Resolution time: {self.resolution_time_minutes} minutes.")
        if self.customer_impact:
            lines.append(f"Customer impact: {self.customer_impact}")
        if self.lesson:
            lines.append(f"Lesson: {self.lesson}")
        lines.extend(self._structured_memory_sections())
        return "\n".join(lines)

    def _structured_memory_sections(self) -> list[str]:
        sections: list[str] = []

        provenance = self._provenance_line()
        if provenance:
            sections.append(provenance)
        if self.evidence:
            rendered = [self._render_evidence(item) for item in self.evidence]
            sections.append("OBSERVED EVIDENCE:\n" + "\n".join(rendered))
        if self.hypotheses:
            rendered = [self._render_hypothesis(item) for item in self.hypotheses]
            sections.append("HYPOTHESES:\n" + "\n".join(rendered))
        if self.investigation:
            rendered = [self._render_investigation(step) for step in self.investigation]
            sections.append("INVESTIGATION:\n" + "\n".join(rendered))
        if self.actions:
            rendered = [self._render_action(action) for action in self.actions]
            sections.append("ACTIONS:\n" + "\n".join(rendered))
        verification = self._render_verification()
        if verification:
            sections.append(verification)
        learning = self._render_learning()
        if learning:
            sections.append(learning)
        return sections

    def _provenance_line(self) -> str:
        parts = []
        if self.source is not None:
            parts.append(f"source={self.source.value}")
        if self.source_case_id:
            parts.append(f"case={self.source_case_id}")
        if self.fault_type:
            parts.append(f"fault={self.fault_type}")
        window = self._time_window_line()
        if window:
            parts.append(window)
        if not parts:
            return ""
        return "SOURCE: " + " | ".join(parts)

    def _time_window_line(self) -> str:
        if self.time_window_start is None and self.time_window_end is None:
            return ""
        start = self.time_window_start.isoformat() if self.time_window_start else "?"
        end = self.time_window_end.isoformat() if self.time_window_end else "?"
        return f"window={start}..{end}"

    @staticmethod
    def _render_evidence(item: EvidenceItem) -> str:
        text = f"- {item.signal}: {item.value}" if item.value is not None else f"- {item.signal}"
        qualifiers = []
        if item.observed_at is not None:
            qualifiers.append(f"observed_at={item.observed_at.isoformat()}")
        if item.provenance != "observed":
            qualifiers.append(f"provenance={item.provenance}")
        if item.stance != "neutral":
            qualifiers.append(f"stance={item.stance}")
        if item.refutes_memory:
            qualifiers.append(f"refutes_memory={item.refutes_memory}")
        if qualifiers:
            text += f" ({'; '.join(qualifiers)})"
        return text

    @staticmethod
    def _render_hypothesis(item: Hypothesis) -> str:
        text = f"- [{item.status}] {item.statement}"
        qualifiers = []
        if item.confidence is not None:
            qualifiers.append(f"confidence={item.confidence}")
        if item.supporting:
            qualifiers.append(f"supporting={', '.join(item.supporting)}")
        if item.contradicting:
            qualifiers.append(f"contradicting={', '.join(item.contradicting)}")
        if qualifiers:
            text += f" ({'; '.join(qualifiers)})"
        return text

    @staticmethod
    def _render_investigation(step: InvestigationStep) -> str:
        text = f"- {step.step_id} | tool={step.tool}"
        if step.target:
            text += f" | target={step.target}"
        text += f" | started_at={step.started_at.isoformat()}"
        if step.result_summary:
            text += f" | result={step.result_summary}"
        if step.result_refs:
            text += f" | refs={', '.join(step.result_refs)}"
        return text

    @staticmethod
    def _render_action(action: AgentAction) -> str:
        text = f"- {action.action_id} | {action.action}"
        if action.target:
            text += f" | target={action.target}"
        if action.parameters:
            params = ", ".join(f"{k}={v}" for k, v in sorted(action.parameters.items()))
            text += f" | params: {params}"
        text += f" | status={action.status}"
        if action.executed_at is not None:
            text += f" | executed_at={action.executed_at.isoformat()}"
        if action.result:
            text += f" | result={action.result}"
        return text

    def _render_verification(self) -> str | None:
        verification = self.verification
        if verification is None:
            return None
        if (
            not verification.metrics_before
            and not verification.metrics_after
            and verification.improved is None
            and verification.status == "pending"
        ):
            return None
        lines = [
            f"VERIFICATION: status={verification.status}, "
            f"improved={verification.improved}"
        ]
        if verification.metrics_before:
            before = ", ".join(
                f"{k}={v}" for k, v in sorted(verification.metrics_before.items())
            )
            lines.append(f"- before: {before}")
        if verification.metrics_after:
            after = ", ".join(
                f"{k}={v}" for k, v in sorted(verification.metrics_after.items())
            )
            lines.append(f"- after: {after}")
        return "\n".join(lines)

    def _render_learning(self) -> str | None:
        learning = self.learning
        if learning is None:
            return None
        if (
            learning.outcome is None
            and not learning.successful_actions
            and not learning.failed_actions
            and learning.lesson is None
            and not learning.suitable_for_hindsight
        ):
            return None
        lines = [
            f"LEARNING: outcome={learning.outcome}, "
            f"suitable_for_hindsight={learning.suitable_for_hindsight}"
        ]
        if learning.successful_actions:
            lines.append(f"- successful: {', '.join(learning.successful_actions)}")
        if learning.failed_actions:
            lines.append(f"- failed: {', '.join(learning.failed_actions)}")
        if learning.lesson:
            lines.append(f"- lesson: {learning.lesson}")
        return "\n".join(lines)

    def to_memory_context(self) -> str:
        context = (
            f"sre incident | {self.service} | {self.environment} | {self.severity.value}"
        )
        if self.source is not None:
            context += f" | source={self.source.value}"
        if self.source_case_id:
            context += f" | case={self.source_case_id}"
        if self.fault_type:
            context += f" | fault={self.fault_type}"
        return context

    def to_memory_metadata(self) -> dict[str, str]:
        metadata = {
            "incident_id": self.incident_id,
            "service": self.service,
            "environment": self.environment,
            "severity": self.severity.value,
        }
        if self.source is not None:
            metadata["source"] = self.source.value
        if self.source_case_id:
            metadata["source_case_id"] = self.source_case_id
        if self.fault_type:
            metadata["fault_type"] = self.fault_type
        if self.time_window_start is not None:
            metadata["time_window_start"] = self.time_window_start.isoformat()
        if self.time_window_end is not None:
            metadata["time_window_end"] = self.time_window_end.isoformat()
        return metadata


class RecallQuery(BaseModel):
    """Input for a memory recall request."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1)
    max_tokens: int = Field(default=4096, ge=256, le=16384)

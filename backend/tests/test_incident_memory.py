"""Tests for Incident memory helpers (legacy + structured sections)."""

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

LEGACY_TEXT = """Incident LEG-1: payment-api (production, P2) experienced an issue.
Symptoms: n/a
Metrics: n/a
Logs: n/a
Root cause: unknown
Actions taken: none recorded
Resolution: unresolved"""


def _structured() -> Incident:
    ts = datetime(2024, 5, 14, 10, 30, tzinfo=timezone.utc)
    return Incident(
        incident_id="SIM-1",
        service="payment-api",
        source=IncidentSource.SIMULATOR,
        source_case_id="sim-1",
        fault_type="bad_deployment",
        time_window_start=ts,
        time_window_end=ts,
        evidence=[
            EvidenceItem(signal="cpu", value="98%", stance="supporting"),
            EvidenceItem(
                signal="db_connections",
                value=42.0,
                stance="contradicting",
                refutes_memory="doc-1",
            ),
        ],
        hypotheses=[
            Hypothesis(
                statement="Recent deployment causing errors",
                status="supported",
                confidence=0.8,
                supporting=["cpu"],
                contradicting=["db_connections"],
            )
        ],
        investigation=[
            InvestigationStep(
                step_id="inv-1",
                started_at=ts,
                tool="metrics_snapshot",
                target="payment-api",
                result_summary="cpu 98%",
            )
        ],
        actions=[
            AgentAction(
                action_id="act-1",
                action="rollback_deployment",
                target="payment-api",
                parameters={"to_version": "1.4.2"},
                status="executed",
                result="5xx falling",
            )
        ],
        verification=Verification(
            metrics_before={"http_5xx_rate": 35.0},
            metrics_after={"http_5xx_rate": 0.4},
            improved=True,
            status="passed",
        ),
        learning=Learning(
            outcome="resolved",
            successful_actions=["act-1"],
            lesson="Rollback first.",
            suitable_for_hindsight=True,
        ),
    )


def test_legacy_memory_text_unchanged() -> None:
    assert Incident(incident_id="LEG-1", service="payment-api").to_memory_text() == LEGACY_TEXT


def test_structured_incident_renders_all_sections() -> None:
    text = _structured().to_memory_text()
    assert text.startswith("Incident SIM-1: payment-api")
    for section in (
        "SOURCE: source=simulator | case=sim-1 | fault=bad_deployment",
        "OBSERVED EVIDENCE:",
        "- cpu: 98% (stance=supporting)",
        "- db_connections: 42.0 (stance=contradicting; refutes_memory=doc-1)",
        "HYPOTHESES:",
        "- [supported] Recent deployment causing errors (confidence=0.8;",
        "INVESTIGATION:",
        "- inv-1 | tool=metrics_snapshot | target=payment-api",
        "ACTIONS:",
        "- act-1 | rollback_deployment | target=payment-api",
        "VERIFICATION: status=passed, improved=True",
        "- before: http_5xx_rate=35.0",
        "- after: http_5xx_rate=0.4",
        "LEARNING: outcome=resolved, suitable_for_hindsight=True",
        "- successful: act-1",
        "- lesson: Rollback first.",
    ):
        assert section in text, section


def test_empty_structured_fields_render_no_sections() -> None:
    text = Incident(incident_id="LEG-1", service="payment-api").to_memory_text()
    for section in (
        "SOURCE:", "OBSERVED EVIDENCE:", "HYPOTHESES:", "INVESTIGATION:",
        "ACTIONS:", "VERIFICATION:", "LEARNING:",
    ):
        assert section not in text
    assert Incident(
        incident_id="LEG-1",
        service="payment-api",
        verification=Verification(),
        learning=Learning(),
    ).to_memory_text() == LEGACY_TEXT


def test_rcaeval_style_incident_invents_no_actions() -> None:
    incident = Incident(
        incident_id="rcaeval-re2ss_user_loss_1",
        service="user",
        source=IncidentSource.RCAEVAL,
        source_case_id="re2ss_user_loss_1",
        fault_type="loss",
        root_cause="loss fault injected in user",
        evidence=[EvidenceItem(signal="front-end_error", value="elevated")],
    )
    text = incident.to_memory_text()
    assert "Root cause: loss fault injected in user" in text
    assert "SOURCE: source=rcaeval | case=re2ss_user_loss_1 | fault=loss" in text
    assert "- front-end_error: elevated" in text
    for section in ("INVESTIGATION:", "ACTIONS:", "VERIFICATION:", "LEARNING:"):
        assert section not in text
    assert "none recorded" in text


def test_failed_learning_rendered() -> None:
    incident = Incident(
        incident_id="SIM-9",
        service="payment-api",
        learning=Learning(
            outcome="unresolved",
            failed_actions=["act-1"],
            lesson="Increasing DB pool did not improve the incident.",
            suitable_for_hindsight=True,
        ),
    )
    text = incident.to_memory_text()
    assert "LEARNING: outcome=unresolved, suitable_for_hindsight=True" in text
    assert "- failed: act-1" in text
    assert "- lesson: Increasing DB pool did not improve the incident." in text


def test_context_contains_source_and_fault() -> None:
    assert Incident(
        incident_id="LEG-1", service="payment-api"
    ).to_memory_context() == "sre incident | payment-api | production | P2"
    assert _structured().to_memory_context() == (
        "sre incident | payment-api | production | P2"
        " | source=simulator | case=sim-1 | fault=bad_deployment"
    )


def test_metadata_contains_source_and_fault() -> None:
    assert Incident(incident_id="LEG-1", service="payment-api").to_memory_metadata() == {
        "incident_id": "LEG-1",
        "service": "payment-api",
        "environment": "production",
        "severity": "P2",
    }
    metadata = _structured().to_memory_metadata()
    assert metadata["source"] == "simulator"
    assert metadata["source_case_id"] == "sim-1"
    assert metadata["fault_type"] == "bad_deployment"
    assert metadata["time_window_start"] == "2024-05-14T10:30:00+00:00"
    assert metadata["time_window_end"] == "2024-05-14T10:30:00+00:00"
    assert "metric_summaries" not in metadata and "evidence" not in metadata

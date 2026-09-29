"""Tests for the RCAEval → Incident loader (historical knowledge only)."""

import pytest

from app.models.incident import IncidentSource
from app.services.rcaeval_loader import rcaeval_record_to_incident


def _ss_record() -> dict:
    """RE2-SS shape: metrics + logs, traces unavailable."""
    return {
        "incident_id": "rcaeval-re2ss_user_loss_1",
        "source": "RCAEval",
        "source_case_id": "re2ss_user_loss_1",
        "dataset": "RE2-SS",
        "service": "user",
        "fault_type": "loss",
        "fault_description": "network packet loss",
        "timestamp": "2024-01-18T22:21:00+00:00",
        "time_window": {
            "start": "2024-01-18T22:09:00+00:00",
            "end": "2024-01-18T22:33:00+00:00",
        },
        "metrics": {
            "column_summary": {
                "user_latency-90": {
                    "pre_mean": 0.0044,
                    "post_mean": 0.0091,
                    "post_max": 0.012,
                    "delta_post_minus_pre": 0.0047,
                },
                "payment_workload": {
                    "pre_mean": 2.0313,
                    "post_mean": 0.3648,
                    "post_max": 2.667,
                    "delta_post_minus_pre": -1.6666,
                },
            },
            "key_indicators": ["user_latency-90", "payment_workload"],
        },
        "logs": {
            "excerpts": [
                {
                    "timestamp": "2024-01-18T22:21:00+00:00",
                    "container": "user",
                    "message": "timeout calling downstream",
                }
            ]
        },
        "traces": None,
        "root_cause": "loss fault injected in user",
        "evidence": ["largest post-injection metric shifts: user_latency-90"],
        "remediation_actions": None,
        "customer_impact": None,
        "lesson": None,
    }


def _tt_record() -> dict:
    """RE2-TT shape: metrics + logs + trace aggregates, many series."""
    return {
        "incident_id": "rcaeval-re2tt_ts-route-service_cpu_2",
        "source_case_id": "re2tt_ts-route-service_cpu_2",
        "dataset": "RE2-TT",
        "service": "ts-route-service",
        "fault_type": "cpu",
        "fault_description": "CPU stress",
        "timestamp": "2024-01-24T06:02:43+00:00",
        "time_window": {
            "start": "2024-01-24T05:50:43+00:00",
            "end": "2024-01-24T06:14:43+00:00",
        },
        "metrics": {
            "column_summary": {
                "ts-route-service_cpu": {
                    "pre_mean": 0.5,
                    "post_mean": 18.4,
                    "post_max": 20.0,
                    "delta_post_minus_pre": 17.9,
                }
            },
            "key_indicators": ["ts-route-service_cpu"],
        },
        "logs": {"excerpts": []},
        "traces": {
            "n_spans_total": 125618,
            "n_spans_post_injection": 62538,
            "post_injection_spans_by_service": {"ts-route-service": 12168},
            "top_operation_groups": [
                {
                    "service": "ts-travel2-service",
                    "operation": "GET",
                    "span_count": 5026,
                    "error_span_count": 0,
                    "duration_p50": 12205.0,
                    "duration_p95": 56173.75,
                }
            ],
        },
        "root_cause": "cpu fault injected in ts-route-service",
        "evidence": [],
    }


def test_basic_conversion_preserves_identity() -> None:
    incident = rcaeval_record_to_incident(_ss_record())
    assert incident.source == IncidentSource.RCAEVAL
    assert incident.source_case_id == "re2ss_user_loss_1"
    assert incident.incident_id == "rcaeval-re2ss_user_loss_1"
    assert incident.service == "user"
    assert incident.fault_type == "loss"
    assert incident.timestamp.isoformat() == "2024-01-18T22:21:00+00:00"
    assert incident.time_window_start is not None
    assert incident.time_window_end is not None


def test_root_cause_is_ground_truth_not_hypothesis() -> None:
    incident = rcaeval_record_to_incident(_ss_record())
    assert incident.root_cause == "loss fault injected in user"
    assert incident.hypotheses == []


def test_no_fabricated_agent_experience() -> None:
    for record in (_ss_record(), _tt_record()):
        incident = rcaeval_record_to_incident(record)
        assert incident.investigation == []
        assert incident.actions == []
        assert incident.actions_taken == []
        assert incident.verification is None
        assert incident.learning is None
        assert incident.lesson is None
        assert incident.resolution is None


def test_provenance_retained() -> None:
    incident = rcaeval_record_to_incident(_ss_record())
    assert incident.source == IncidentSource.RCAEVAL
    assert incident.source_case_id == "re2ss_user_loss_1"
    assert all(item.provenance == "observed" for item in incident.evidence)
    assert {item.signal for item in incident.evidence} == {
        "user_latency-90",
        "payment_workload",
    }
    assert "user_latency-90" in incident.metrics  # original names preserved


def test_trace_summary_compact_and_nullable() -> None:
    assert rcaeval_record_to_incident(_ss_record()).trace_summary is None
    summary = rcaeval_record_to_incident(_tt_record()).trace_summary
    assert summary is not None
    assert summary["n_spans_total"] == 125618
    assert len(summary["top_operation_groups"]) <= 5


def test_missing_optional_fields_do_not_crash() -> None:
    incident = rcaeval_record_to_incident({"source_case_id": "re2ss_user_mem_3"})
    assert incident.source == IncidentSource.RCAEVAL
    assert incident.incident_id == "rcaeval-re2ss_user_mem_3"
    assert incident.service == "unknown"
    assert incident.fault_type is None
    assert incident.metric_summaries == {}
    assert incident.metrics == {}
    assert incident.logs == []
    assert incident.evidence == []
    assert incident.trace_summary is None
    assert incident.root_cause is None


def test_missing_case_identifier_raises() -> None:
    with pytest.raises(ValueError):
        rcaeval_record_to_incident({"service": "user"})
    with pytest.raises(ValueError):
        rcaeval_record_to_incident("not-a-dict")  # type: ignore[arg-type]

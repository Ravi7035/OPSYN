"""RCAEval record → unified Incident loader.

Historical knowledge only: converts one RCAEval processed record
(`data/rcaeval/processed/incidents.jsonl` row) into an `Incident`.
RCAEval provides diagnostic evidence and ground-truth root cause; it
provides no remediation, recovery, lessons, or agent reasoning, so the
agent-experience sections (hypotheses, investigation, actions,
verification, learning) are always left empty — never invented.
"""

from datetime import datetime

from app.models.incident import (
    EvidenceItem,
    Incident,
    IncidentSource,
    MetricSummary,
)

_MAX_TRACE_GROUPS = 5


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _compact_number(value: float | None) -> str:
    return f"{value:.4g}" if value is not None else "n/a"


def rcaeval_record_to_incident(record: dict) -> Incident:
    """Convert one RCAEval record dict into an `Incident`.

    Raises:
        ValueError: if the record carries no usable case identifier.
    """
    if not isinstance(record, dict):
        raise ValueError("RCAEval record must be a dict.")

    source_case_id = record.get("source_case_id") or record.get("incident_id")
    if not source_case_id:
        raise ValueError("RCAEval record has no case identifier.")
    source_case_id = str(source_case_id)
    incident_id = str(record.get("incident_id") or f"rcaeval-{source_case_id}")

    service = str(record.get("service") or "unknown")
    fault_type = record.get("fault_type")
    fault_type = str(fault_type) if fault_type else None

    timestamp = _parse_time(record.get("timestamp"))
    window = record.get("time_window") or {}
    window_start = _parse_time(window.get("start") if isinstance(window, dict) else None)
    window_end = _parse_time(window.get("end") if isinstance(window, dict) else None)
    if timestamp is None:
        timestamp = window_start  # fall back to window start, never "now"

    metrics_block = record.get("metrics") or {}
    column_summary = metrics_block.get("column_summary") or {}
    metric_summaries: dict[str, MetricSummary] = {}
    for name, summary in column_summary.items():
        if not isinstance(summary, dict):
            continue
        metric_summaries[str(name)] = MetricSummary(
            pre_mean=_as_float(summary.get("pre_mean")),
            post_mean=_as_float(summary.get("post_mean")),
            post_max=_as_float(summary.get("post_max")),
            delta=_as_float(summary.get("delta_post_minus_pre")),
        )

    key_indicators = metrics_block.get("key_indicators") or []
    legacy_metrics: dict[str, str] = {}
    evidence: list[EvidenceItem] = []
    for name in key_indicators:
        summary = metric_summaries.get(str(name))
        if summary is None:
            continue
        legacy_metrics[str(name)] = (
            f"post_mean={_compact_number(summary.post_mean)}, "
            f"delta={_compact_number(summary.delta)}"
        )
        evidence.append(
            EvidenceItem(
                signal=str(name),
                value=f"delta={_compact_number(summary.delta)}",
                provenance="observed",
                stance="supporting",
            )
        )

    logs_block = record.get("logs") or {}
    logs: list[str] = []
    for excerpt in logs_block.get("excerpts") or []:
        if not isinstance(excerpt, dict):
            continue
        logs.append(
            f"[{excerpt.get('timestamp', '?')}] "
            f"{excerpt.get('container', '?')}: {excerpt.get('message', '')}"
        )

    symptoms: list[str] = []
    fault_description = record.get("fault_description")
    if fault_description:
        symptoms.append(f"{fault_description} in {service}")
    for line in record.get("evidence") or []:
        if isinstance(line, str) and line.startswith("largest post-injection"):
            symptoms.append(line)
            break

    traces_block = record.get("traces")
    trace_summary: dict | None = None
    if isinstance(traces_block, dict):
        trace_summary = {
            "n_spans_total": traces_block.get("n_spans_total"),
            "n_spans_post_injection": traces_block.get("n_spans_post_injection"),
            "spans_by_service": traces_block.get("post_injection_spans_by_service") or {},
            "top_operation_groups": (
                traces_block.get("top_operation_groups") or []
            )[:_MAX_TRACE_GROUPS],
        }

    incident_kwargs: dict = {
        "incident_id": incident_id,
        "service": service,
        "symptoms": symptoms,
        "logs": logs,
        "metrics": legacy_metrics,
        "root_cause": record.get("root_cause"),
        "source": IncidentSource.RCAEVAL,
        "source_case_id": source_case_id,
        "fault_type": fault_type,
        "time_window_start": window_start,
        "time_window_end": window_end,
        "metric_summaries": metric_summaries,
        "trace_summary": trace_summary,
        "evidence": evidence,
    }
    if timestamp is not None:
        incident_kwargs["timestamp"] = timestamp
    # If no timing exists anywhere in the record the model default applies;
    # such records are traceable via their (absent) time_window_* fields.
    return Incident(**incident_kwargs)

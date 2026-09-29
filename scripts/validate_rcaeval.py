"""Validate data/rcaeval/processed/incidents.jsonl.

Checks JSON validity per line, reports incident count, missing fields,
telemetry availability, fault-type distribution, and prints three
representative incidents.

Usage (from the OPSYN project root):
    python scripts/validate_rcaeval.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JSONL = PROJECT_ROOT / "data" / "rcaeval" / "processed" / "incidents.jsonl"

REQUIRED_FIELDS = [
    "incident_id", "source", "source_case_id", "dataset", "suite",
    "system", "service", "fault_type", "timestamp", "metrics",
    "logs", "traces", "root_cause", "evidence", "source_type",
]
ALWAYS_NULL_FIELDS = ["remediation_actions", "customer_impact", "lesson"]


def main() -> None:
    incidents: list[dict] = []
    invalid_lines: list[int] = []
    with JSONL.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                incidents.append(json.loads(line))
            except json.JSONDecodeError:
                invalid_lines.append(lineno)

    print(f"File: {JSONL}")
    print(f"Valid incidents: {len(incidents)}, invalid lines: {len(invalid_lines)}")
    if invalid_lines:
        print(f"  invalid line numbers: {invalid_lines}")

    missing: Counter[str] = Counter()
    for incident in incidents:
        for field in REQUIRED_FIELDS:
            if incident.get(field) is None:
                missing[field] += 1
    print("\nMissing required fields (count of incidents lacking each):")
    for field in REQUIRED_FIELDS:
        print(f"  {field}: {missing[field]}")

    print("\nUnavailable-by-design fields (expected null for every RCAEval incident):")
    for field in ALWAYS_NULL_FIELDS:
        n_null = sum(1 for i in incidents if i.get(field) is None)
        print(f"  {field}: null in {n_null}/{len(incidents)}")

    with_logs = sum(1 for i in incidents if i.get("logs"))
    with_traces = sum(1 for i in incidents if i.get("traces"))
    with_metrics = sum(1 for i in incidents if i.get("metrics"))
    print(f"\nTelemetry availability: metrics {with_metrics}, logs {with_logs}, "
          f"traces {with_traces} (of {len(incidents)})")

    print("\nFault-type distribution:")
    for fault, count in Counter(i["fault_type"] for i in incidents).most_common():
        print(f"  {fault}: {count}")
    print("\nDataset distribution:")
    for dataset, count in Counter(i["dataset"] for i in incidents).most_common():
        print(f"  {dataset}: {count}")

    print("\n--- 3 representative incidents ---")
    seen: set[str] = set()
    shown = 0
    for incident in incidents:
        key = (incident["dataset"], incident["fault_type"])
        if key in seen:
            continue
        seen.add(key)
        metrics = incident["metrics"] or {}
        logs = incident["logs"] or {}
        traces = incident.get("traces") or {}
        print(f"\n[{incident['incident_id']}] {incident['system']} | "
              f"service={incident['service']} | fault={incident['fault_type']} | "
              f"ts={incident['timestamp']}")
        print(f"  metrics: {metrics.get('n_series')} series x "
              f"{metrics.get('n_timesteps')} steps; "
              f"top shifts: {', '.join((metrics.get('key_indicators') or [])[:3])}")
        print(f"  logs: {logs.get('n_logs_total')} total, "
              f"{logs.get('n_logs_post_injection')} post-injection, "
              f"{len(logs.get('excerpts') or [])} excerpts")
        print(f"  traces: {traces.get('n_spans_total', 'n/a')} spans, "
              f"{len(traces.get('top_operation_groups') or [])} op groups" if traces else "  traces: none")
        print(f"  root_cause: {incident['root_cause']}")
        shown += 1
        if shown == 3:
            break


if __name__ == "__main__":
    main()

"""Convert selected RCAEval cases into normalized incident records.

Reads original per-case telemetry from data/rcaeval/selected/<case>/
(metrics.parquet, logs.parquet, traces.parquet, inject_time.txt) plus the
case metadata in data/rcaeval/selected_cases.csv, and writes one JSON object
per line to data/rcaeval/processed/incidents.jsonl.

Nothing is invented: every value is either copied verbatim from RCAEval,
computed deterministically from its telemetry (labeled as such), or left
null with an explicit reason. RCAEval contains no remediation actions,
postmortems, lessons learned, investigation steps, or customer-impact
labels, so those fields are always null.

Telemetry is summarized rather than embedded in full (a single case can
hold 100k+ log lines and 500k+ spans) so the output stays usable as a
Hindsight memory payload. Sampling is deterministic: earliest timestamp
first, error-keyword matches preferred for log excerpts.

Usage (from the OPSYN project root):
    python scripts/prepare_rcaeval.py
    python scripts/prepare_rcaeval.py --help
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SELECTION_CSV = PROJECT_ROOT / "data" / "rcaeval" / "selected_cases.csv"
SELECTED_DIR = PROJECT_ROOT / "data" / "rcaeval" / "selected"
OUTPUT_JSONL = PROJECT_ROOT / "data" / "rcaeval" / "processed" / "incidents.jsonl"

MAX_LOG_EXCERPTS = 60
MAX_TRACE_GROUPS = 40
MAX_KEY_INDICATORS = 10
ERROR_KEYWORDS = (
    "error", "exception", "fail", "timeout", "refused", "panic",
    "fatal", "warn", "denied", "unavailable", "crash",
)

UNAVAILABLE = "unavailable_in_rcaeval"


def to_iso(ts: int | float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def clean_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def summarize_metrics(metrics: pd.DataFrame, inject_time: int) -> dict:
    """Per-column pre/post-injection summary. All values are computed."""
    pre = metrics[metrics["time"] < inject_time]
    post = metrics[metrics["time"] >= inject_time]
    columns = [c for c in metrics.columns if c != "time"]
    summary: dict[str, dict] = {}
    for column in columns:
        pre_mean = clean_number(pre[column].mean()) if len(pre) else None
        post_mean = clean_number(post[column].mean()) if len(post) else None
        post_max = clean_number(post[column].max()) if len(post) else None
        delta = (
            (post_mean - pre_mean)
            if pre_mean is not None and post_mean is not None
            else None
        )
        summary[column] = {
            "pre_mean": pre_mean,
            "post_mean": post_mean,
            "post_max": post_max,
            "delta_post_minus_pre": delta,
        }
    ranked = sorted(
        ((c, s) for c, s in summary.items() if s["delta_post_minus_pre"] is not None),
        # Symmetric relative shift in [0, 2]: unit-independent, so a byte
        # counter cannot drown out a percentage series on scale alone.
        key=lambda item: abs(item[1]["delta_post_minus_pre"] or 0.0)
        / (
            (abs(item[1]["pre_mean"] or 0.0) + abs(item[1]["post_mean"] or 0.0)) / 2
            + 1e-9
        ),
        reverse=True,
    )
    return {
        "n_timesteps": int(len(metrics)),
        "n_series": len(columns),
        "time_start": to_iso(metrics["time"].min()),
        "time_end": to_iso(metrics["time"].max()),
        "column_summary": summary,
        "key_indicators": [c for c, _ in ranked[:MAX_KEY_INDICATORS]],
        "derivation": "computed_pre_post_summary_full_matrix_not_embedded",
    }


def sample_logs(logs: pd.DataFrame, inject_time: int) -> dict:
    """Deterministic verbatim excerpts plus per-container counts."""
    ordered = logs.sort_values("timestamp").reset_index(drop=True)
    post = ordered[ordered["timestamp"] >= inject_time]
    counts = post["container_name"].value_counts().to_dict()
    excerpts: list[dict] = []

    def take(frame: pd.DataFrame, limit: int) -> None:
        for _, row in frame.head(limit).iterrows():
            if len(excerpts) >= MAX_LOG_EXCERPTS:
                return
            excerpts.append(
                {
                    "timestamp": to_iso(row["timestamp"]),
                    "container": str(row["container_name"]),
                    "message": str(row["message"])[:2000],
                }
            )

    lowered = post["message"].astype(str).str.lower()
    error_like = post[lowered.str.contains("|".join(ERROR_KEYWORDS), na=False)]
    take(error_like, MAX_LOG_EXCERPTS)
    take(post, MAX_LOG_EXCERPTS)
    return {
        "n_logs_total": int(len(ordered)),
        "n_logs_post_injection": int(len(post)),
        "post_injection_counts_by_container": {str(k): int(v) for k, v in counts.items()},
        "excerpts": excerpts,
        "excerpt_policy": "verbatim_first_error_keyword_then_earliest_post_injection",
    }


def summarize_traces(traces: pd.DataFrame, inject_time: int) -> dict:
    """Aggregate spans per (service, operation), split pre/post injection."""
    frame = traces.copy()
    frame["epoch"] = pd.to_numeric(frame["startTimeMillis"], errors="coerce") // 1000
    post = frame[frame["epoch"] >= inject_time]
    groups: list[dict] = []
    grouped = post.groupby(["serviceName", "operationName"], dropna=False)
    for (service, operation), group in grouped:
        durations = pd.to_numeric(group["duration"], errors="coerce").dropna()
        errors = group[group["statusCode"].fillna(0).astype(str) != "0"]
        groups.append(
            {
                "service": None if pd.isna(service) else str(service),
                "operation": None if pd.isna(operation) else str(operation),
                "span_count": int(len(group)),
                "error_span_count": int(len(errors)),
                "duration_p50": clean_number(durations.quantile(0.5)) if len(durations) else None,
                "duration_p95": clean_number(durations.quantile(0.95)) if len(durations) else None,
            }
        )
    groups.sort(key=lambda g: g["span_count"], reverse=True)
    by_service: dict[str, int] = (
        post["serviceName"].fillna("unknown").astype(str).value_counts().to_dict()
    )
    return {
        "n_spans_total": int(len(frame)),
        "n_spans_post_injection": int(len(post)),
        "post_injection_spans_by_service": {str(k): int(v) for k, v in by_service.items()},
        "top_operation_groups": groups[:MAX_TRACE_GROUPS],
        "derivation": "computed_span_aggregation_raw_spans_not_embedded",
    }


def convert_case(case_dir: Path, meta: dict) -> dict:
    inject_time = int((case_dir / "inject_time.txt").read_text().strip())
    metrics_df = pd.read_parquet(case_dir / "metrics.parquet")
    logs_df = pd.read_parquet(case_dir / "logs.parquet")

    traces_path = case_dir / "traces.parquet"
    traces_summary = (
        summarize_traces(pd.read_parquet(traces_path), inject_time)
        if traces_path.exists()
        else None
    )

    root_service = str(meta["root_cause_service"])
    fault = str(meta["fault"])
    evidence = [
        f"fault '{fault}' ({meta['fault_description']}) injected into "
        f"'{root_service}' at {to_iso(inject_time)}",
        f"{len(metrics_df)} metric timesteps x {len(metrics_df.columns) - 1} series",
        f"{len(logs_df)} log lines total",
    ]
    if traces_summary is not None:
        evidence.append(f"{traces_summary['n_spans_total']} spans total")
    key_indicators = summarize_metrics(metrics_df, inject_time)["key_indicators"]
    if key_indicators:
        evidence.append(f"largest post-injection metric shifts: {', '.join(key_indicators[:5])}")

    return {
        "incident_id": f"rcaeval-{meta['case']}",
        "source": "RCAEval",
        "source_case_id": str(meta["case"]),
        "dataset": str(meta["dataset"]),
        "suite": str(meta["suite"]),
        "system": str(meta["system_name"]),
        "service": root_service,
        "fault_type": fault,
        "fault_description": str(meta["fault_description"]),
        "timestamp": to_iso(inject_time),
        "time_window": {
            "start": to_iso(meta["time_start"]),
            "end": to_iso(meta["time_end"]),
        },
        "metrics": summarize_metrics(metrics_df, inject_time),
        "logs": sample_logs(logs_df, inject_time),
        "traces": traces_summary,
        "root_cause": f"{fault} fault injected in {root_service}",
        "evidence": evidence,
        "remediation_actions": None,
        "customer_impact": None,
        "lesson": None,
        "unavailable_fields_reason": UNAVAILABLE,
        "source_type": "public_benchmark",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=SELECTION_CSV)
    parser.add_argument("--data-dir", type=Path, default=SELECTED_DIR)
    parser.add_argument("--out", type=Path, default=OUTPUT_JSONL)
    args = parser.parse_args()

    selection = pd.read_csv(args.selection)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.out.open("w", encoding="utf-8") as handle:
        for _, row in selection.iterrows():
            case_dir = args.data_dir / row["case"]
            if not case_dir.is_dir():
                print(f"SKIP {row['case']}: not downloaded at {case_dir}")
                continue
            incident = convert_case(case_dir, row.to_dict())
            handle.write(json.dumps(incident) + "\n")
            written += 1
    print(f"Wrote {written}/{len(selection)} incidents to {args.out}")


if __name__ == "__main__":
    main()

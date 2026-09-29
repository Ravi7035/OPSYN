# RCAEval data for OPSYN

## Source

- Benchmark: **RCAEval** — root-cause-analysis benchmark for microservice systems
  (WWW'25 / ASE'24 / FSE'26 papers).
- GitHub: https://github.com/phamquiluan/RCAEval
- Hugging Face (recommended access, Parquet): https://huggingface.co/datasets/phamquiluan/RCAEval
- License: MIT (code and datasets as distributed by the authors).
- HF snapshot used: `afeacb11bcc94dadfd1c8f483ee4377b2b8b614e`
  (`cases.parquet` preserved at `data/rcaeval/raw/cases.parquet`).

Access method: `huggingface_hub.snapshot_download` with per-case
`allow_patterns` (e.g. `re2ob_checkoutservice_cpu_2/*`), so only selected
cases are fetched — never the full 3.4 GB dump. A suite-level fetch would be
`allow_patterns="re2*"`.

## Selected cases (24)

| Dataset | Cases | Faults | Telemetry |
|---|---|---|---|
| RE2-OB (Online Boutique) | 12 | cpu, mem, disk, delay, loss, socket × 2 | metrics + logs + traces |
| RE2-TT (Train Ticket) | 6 | cpu, mem, disk, delay, loss, socket × 1 | metrics + logs + traces |
| RE2-SS (Sock Shop) | 6 | cpu, mem, disk, delay, loss, socket × 1 | metrics + logs (no traces exist for SS) |

Full per-case metadata (case ID, suite, system, fault, root-cause service,
injection time, telemetry sizes, local path):
`data/rcaeval/selected_cases.csv`.

### Why these

- RE2 preferred: only the RE suites with metrics + logs (+ traces where
  available), giving the agent evidence to reason over instead of bare metric
  series (RE1 is metrics-only; RE3 is code-level faults, out of scope for now).
- All six RE2 fault types represented across three systems → failure diversity.
- Within each (dataset, fault) group the smallest `(n_logs + n_traces)`
  repetitions were picked → total download ≈ 150 MB instead of 3.4 GB.
- 18/24 cases include traces (all RE2-OB and RE2-TT cases).

## Original vs transformed vs unavailable

- **Original (copied verbatim):** case ID, dataset/suite/system, fault type and
  description, root-cause service, injection timestamp, time window, log
  message excerpts, `root_cause` label (`"<fault> fault injected in
  <service>"` — ground truth from the benchmark index).
- **Transformed (deterministically computed, labeled in the record):**
  per-metric pre/post-injection mean/max/delta summaries and top shifting
  indicators; per-container post-injection log counts; per-(service, operation)
  span aggregates with error counts and p50/p95 durations; `evidence` strings
  derived from those computations. Full matrices (all timesteps, all log
  lines, all spans) stay in `selected/` and are NOT embedded.
- **Unavailable (always null, never invented):** `remediation_actions`,
  `customer_impact`, `lesson` — RCAEval is a fault-injection benchmark and
  ships none of these.

## Layout

```text
data/rcaeval/
├── raw/cases.parquet            # benchmark index (735 cases), preserved
├── selected/<case>/             # 24 original cases, unmodified
│   └── metrics.parquet, logs.parquet, traces.parquet*, inject_time.txt
├── selected_cases.csv           # metadata index for the 24 cases
├── processed/incidents.jsonl    # 24 normalized incidents, one per line
└── README.md
```

Per-case schemas: metrics (`time` + `<service>_<cpu|mem|diskio|socket|
workload|error|latency-50|latency-90>`), logs (`timestamp, container_name,
message`), traces (`time, traceID, spanID, serviceName, methodName,
operationName, parentSpanID, startTimeMillis, startTime, duration,
statusCode`). `*` RE2-SS cases have no `traces.parquet`.

## Reproduce

Requires Python 3.11+ with `huggingface_hub`, `pandas`, `pyarrow`:

```powershell
cd <OPSYN root>
pip install huggingface_hub pandas pyarrow
python scripts/prepare_rcaeval.py    # needs selected/ + selected_cases.csv, or re-download (see below)
python scripts/validate_rcaeval.py
```

To re-download the 24 cases from scratch (after deleting `selected/`):

```powershell
python -c "import pandas as pd; from huggingface_hub import snapshot_download; sel = pd.read_csv('data/rcaeval/selected_cases.csv'); snapshot_download(repo_id='phamquiluan/RCAEval', repo_type='dataset', allow_patterns=[c+'/*' for c in sel['case']], local_dir='data/rcaeval/selected')"
python scripts/prepare_rcaeval.py
```

## Limitations

- Faults are injected and single-root-cause by construction — simpler than
  real production incidents (no cascading unknowns, no remediation history).
- No remediation, impact, or lesson labels exist; Hindsight memories built
  from this data teach *diagnosis evidence*, not *response actions*.
- Telemetry in `incidents.jsonl` is summarized/sampled (see policies in
  `scripts/prepare_rcaeval.py`); full fidelity requires reading `selected/`.
- Only RE2 suites are covered (24/735 cases); RE1/RE3/TORAI remain for later.

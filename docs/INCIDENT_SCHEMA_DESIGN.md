# OPSYN Unified Incident Schema — Design Report

Status: **design only — nothing implemented.** No simulator, agent, or
Hindsight changes are made by this document.

Goal: the smallest clean extension to the current schema so one incident
representation supports the full OPSYN learning loop
(Observe → Recall → Hypothesize → Investigate → Act → Verify → Learn) for
both historical RCAEval records and future payment-simulator experiences —
without making RCAEval records look like simulator experiences.

## 1. Current schema discovered

### 1.1 `backend/app/models/incident.py` — the only domain model

```python
class Severity(str, Enum): P1_CRITICAL="P1" … P4_LOW="P4"

class Incident(BaseModel):          # extra="allow"
    incident_id: str
    service: str
    environment: str = "production"
    severity: Severity = P2_HIGH
    timestamp: datetime             # single point in time
    symptoms: list[str]             # flat text
    logs: list[str]                 # flat text lines
    metrics: dict[str, str]         # flat string map
    root_cause: str | None
    actions_taken: list[str]        # flat text
    resolution: str | None
    resolution_time_minutes: float | None
    customer_impact: str | None
    lesson: str | None
    # helpers: to_memory_text(), to_memory_context(), to_memory_metadata()

class RecallQuery(BaseModel):
    query: str; max_tokens: int = 4096
```

Dependents of this schema (all import `Incident` or its helpers):
`app/services/hindsight_service.py` (`retain_incident`, `SAMPLE_INCIDENT`),
`app/api/routes/memory.py` (via the service only), `app/core/dependencies.py`
(singleton wiring), `app/main.py` (router wiring), `tests/test_hindsight.py`.

### 1.2 RCAEval processed format (`data/rcaeval/processed/incidents.jsonl`, 24 records)

Plain-JSON (not Pydantic) records with keys:
`incident_id, source, source_case_id, dataset, suite, system, service,
fault_type, fault_description, timestamp, time_window{start,end},
metrics{n_timesteps, n_series, time_start/end, column_summary{col:
{pre_mean, post_mean, post_max, delta_post_minus_pre}}, key_indicators[10],
derivation}, logs{n_logs_total, n_logs_post_injection,
post_injection_counts_by_container, excerpts[{timestamp, container,
message}], excerpt_policy}, traces{…aggregates…} | null, root_cause,
evidence[list[str]], remediation_actions=null, customer_impact=null,
lesson=null, unavailable_fields_reason, source_type`.

Produced by `scripts/prepare_rcaeval.py`; validated by
`scripts/validate_rcaeval.py`. Telegraphs are **summarized, never
embedded in full** — the right granularity for memory payloads.

### 1.3 Hindsight integration (`app/services/hindsight_service.py`)

The only SDK touchpoint. `retain_incident(incident: Incident)` renders
`to_memory_text()` → `aretain(content, context, metadata, document_id,
tags=["sre","incident",service,environment])`. `recall_incidents` returns
`[{text, score, metadata}]`. The service takes any object with the three
`to_memory_*` helpers — so schema evolution is contained if the new model
keeps those helpers with the same signatures.

### 1.4 What does not exist yet

No telemetry models, no evidence/diagnosis models, no action/remediation
models, no investigation/verification/learning models, no agent models, no
`source`/provenance field, no timeline beyond one timestamp, no trace field.

## 2. Current limitations (mapped to the learning loop)

| Loop stage | Gap in current schema |
|---|---|
| Observe | `metrics: dict[str,str]` is string-only and flat — cannot hold the numeric pre/post summaries RCAEval already computes; no `traces` slot; single `timestamp`, no window |
| Recall | No `source` / `fault_type` fields → cannot tag or filter memories by provenance ("rcaeval analogue" vs "simulator experience") |
| Hypothesize | No hypothesis object; `root_cause` is a bare string mixing benchmark ground truth and future agent conclusions |
| Investigate | No investigation-step record (tool used, result, timestamp) |
| Act | `actions_taken: list[str]` cannot carry target, parameters, or per-action result |
| Verify | No before/after metric comparison, no pass/fail status |
| Learn | `lesson` exists as free text but no outcome enum, no success/failure action refs, no "suitable for Hindsight" flag |
| Evidence vs conclusions | `symptoms`/`logs` (observed) and `root_cause`/`resolution` (concluded) sit side by side with no supporting/contradicting structure — the agent cannot represent "memory says X, current evidence contradicts X" |

## 3. Proposed schema changes (minimal extension, no duplication)

**Keep `Incident` as the envelope; keep every existing field and helper
signature.** Add six optional submodels in the same file
(`backend/app/models/incident.py`) — all `None`/empty by default so every
current caller, test, and the sample incident keep working:

```python
class IncidentSource(str, Enum):
    RCAEVAL = "rcaeval"; SIMULATOR = "simulator"; PRODUCTION = "production"

class MetricSummary(BaseModel):          # one entry per metric series
    pre_mean: float | None; post_mean: float | None
    post_max: float | None; delta: float | None

class EvidenceItem(BaseModel):           # OBSERVED, never a conclusion
    signal: str                          # e.g. "db_connections", "http_5xx_rate"
    value: str | float | None            # observed value (arbitrary metric names OK)
    observed_at: datetime | None = None
    provenance: str = "observed"         # "observed" | "recalled_memory:<id>"
    stance: str = "neutral"              # "neutral" | "supporting" | "contradicting"
    refutes_memory: str | None = None    # memory id this contradicts, if any

class Hypothesis(BaseModel):             # AGENT CONCLUSION (or benchmark label)
    statement: str
    status: str = "considered"           # "considered"|"supported"|"rejected"|"confirmed"
    confidence: float | None = None      # optional, 0..1; omit when unknown
    supporting: list[str] = []           # evidence signals backing it
    contradicting: list[str] = []        # evidence signals against it

class InvestigationStep(BaseModel):
    step_id: str; started_at: datetime
    tool: str                            # observation/tool used, e.g. "metrics_snapshot"
    target: str | None = None
    result_summary: str; result_refs: list[str] = []

class AgentAction(BaseModel):
    action_id: str; action: str           # e.g. "increase_db_pool"
    target: str | None = None
    parameters: dict[str, str | float] = {}
    status: str = "proposed"             # "proposed"|"executed"|"failed"|"rolled_back"
    executed_at: datetime | None = None
    result: str | None = None

class Verification(BaseModel):
    metrics_before: dict[str, float] = {}
    metrics_after: dict[str, float] = {}
    improved: bool | None = None
    status: str = "pending"              # "pending"|"passed"|"failed"

class Learning(BaseModel):
    outcome: str | None = None           # "resolved"|"unresolved"|"escalated"
    successful_actions: list[str] = []   # action_ids
    failed_actions: list[str] = []
    lesson: str | None = None
    suitable_for_hindsight: bool = False
```

New optional fields on `Incident` (all default `None`/empty):

```python
    source: IncidentSource | None = None
    source_case_id: str | None = None
    fault_type: str | None = None
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    metric_summaries: dict[str, MetricSummary] = {}  # arbitrary names → §7 OK
    trace_summary: dict | None = None                # passthrough aggregate
    evidence: list[EvidenceItem] = []
    hypotheses: list[Hypothesis] = []
    investigation: list[InvestigationStep] = []
    actions: list[AgentAction] = []                  # structured; actions_taken stays for text
    verification: Verification | None = None
    learning: Learning | None = None
```

Deliberately **not** added: a scoring/ranking system (recall scores already
come from Hindsight; `confidence` is optional metadata, not a mechanism),
per-metric hardcoded fields (dict keys stay free-form), a second parallel
model (one envelope, optional sections).

## 4. Field-by-field explanation

- `source` / `source_case_id` — provenance. Lets recall queries and tags
  distinguish "historical analogue" from "lived simulator experience".
  RCAEval loader sets `rcaeval` + original case id.
- `fault_type` — shared vocabulary (`cpu/mem/disk/delay/loss/socket`,
  later `bad_deployment`) so recall bridges RCAEval and simulator memories.
- `time_window_start/end` — RCAEval cases are 12–70 min windows; one
  `timestamp` cannot represent that. `timestamp` stays as incident start.
- `metric_summaries` — numeric home for what RCAEval already computes
  (`column_summary`) and whatever the simulator emits; free-form keys keep
  §7 compatibility without schema edits per new signal.
- `trace_summary` — untyped passthrough for the aggregate the prepare
  script already produces; simulator traces later fit the same slot.
- `evidence[]` — observations only. `stance` + `refutes_memory` give the
  "memory says pool exhaustion, current DB connections = 42%" case a
  first-class representation with no scoring machinery.
- `hypotheses[]` — conclusions, kept separate from evidence; `supporting`
  / `contradicting` name evidence signals, not free prose.
- `investigation[]` / `actions[]` / `verification` / `learning` — the
  Act→Verify→Learn trail. RCAEval records leave all four empty/null, which
  is precisely how "no invented remediation" is enforced by construction.

## 5. RCAEval example using the proposed schema

`rcaeval-re2ss_user_loss_1` (user/packet-loss; payment only a bystander):

```python
Incident(
    incident_id="rcaeval-re2ss_user_loss_1",
    source="rcaeval", source_case_id="re2ss_user_loss_1",
    service="user", environment="production", severity="P2",
    timestamp="2024-01-18T22:21:00+00:00",          # injection time
    time_window_start="2024-01-18T22:09:00+00:00",
    time_window_end="2024-01-18T22:33:00+00:00",
    fault_type="loss",
    metric_summaries={"user_latency-90": MetricSummary(pre_mean=0.0044, …),
                      "payment_workload": MetricSummary(pre_mean=2.03, post_mean=0.36, …),
                      …},                            # from column_summary, all series
    trace_summary=None,                             # SS has no traces — null, not faked
    evidence=[EvidenceItem(signal="front-end_error", value="elevated post-injection"),
              EvidenceItem(signal="payment_workload", value=0.36, …)],
    hypotheses=[Hypothesis(statement="packet loss in user service",
                            status="confirmed")],    # benchmark ground truth
    symptoms=["elevated front-end and orders errors", …],  # legacy text kept
    logs=[…60 verbatim excerpts…],
    root_cause="loss fault injected in user",        # legacy field kept
    investigation=[], actions=[], verification=None, learning=None,
)
```

Note: `remediation/actions/verification/learning` are empty — the record is
honest about being diagnosis-only.

## 6. Payment simulator example using the proposed schema

```python
Incident(
    incident_id="sim-0007", source="simulator",
    service="payment-api", environment="production", severity="P1",
    timestamp=<start>, time_window_start=<start>, time_window_end=<start+20m>,
    fault_type="bad_deployment",
    metric_summaries={"cpu": …, "db_connections": …, "http_5xx_rate": …,
                      "p95_latency_s": …, "redis_healthy": …, "queue_depth": …,
                      "deployment_recent": …},       # free-form keys, no schema change
    evidence=[EvidenceItem(signal="cpu", value="97%"),
              EvidenceItem(signal="http_5xx_rate", value="32%"),
              EvidenceItem(signal="db_connections", value="41%"),
              EvidenceItem(signal="deployment_recent", value=True)],
    hypotheses=[Hypothesis(statement="Recent deployment causing elevated CPU and errors",
                            status="supported",
                            supporting=["cpu", "http_5xx_rate", "deployment_recent"],
                            contradicting=["db_connections"],
                            confidence=0.8)],
    …
)
```

The contradicting slot carries the §5 scenario directly: the recalled
"pool exhaustion" memory is countered by `db_connections=41%` recorded as
`EvidenceItem(stance="contradicting", refutes_memory="<hindsight-doc-id>")`.

## 7. Agent action/verification example

```python
investigation=[InvestigationStep(step_id="inv-1", started_at=…,
    tool="metrics_snapshot", target="payment-api",
    result_summary="cpu 97%, 5xx 32%, db_connections 41%")],
actions=[AgentAction(action_id="act-1", action="rollback_deployment",
    target="payment-api", parameters={"to_version": "1.4.2"},
    status="executed", executed_at=…, result="deploy reverted, 5xx falling")],
verification=Verification(
    metrics_before={"http_5xx_rate": 32.0, "cpu": 97.0},
    metrics_after={"http_5xx_rate": 0.4, "cpu": 21.0},
    improved=True, status="passed"),
learning=Learning(outcome="resolved", successful_actions=["act-1"],
    failed_actions=[],
    lesson="P95/5xx spike with recent deploy and normal DB pool → rollback first",
    suitable_for_hindsight=True),
```

Only records with `learning.suitable_for_hindsight=True` (plus all RCAEval
diagnostic records) are retained — the gate that keeps failed or
unverified episodes out of organizational memory.

## 8. Hindsight memory representation

No Hindsight SDK or service redesign needed. Extend the three helpers:

- `to_memory_text()` renders **present sections only**, in fixed order:
  identity/source → observed evidence → hypotheses/root cause → (if any)
  investigation → action → verification → learning. RCAEval renders stop
  after root cause plus the explicit line
  `"Remediation: not recorded in source benchmark."` — the anti-invention
  guarantee, in text.
- `to_memory_context()` gains source and fault:
  `"sre incident | payment-api | production | P1 | simulator | bad_deployment"`.
- `to_memory_metadata()` gains `source` and `fault_type` keys (keeps the
  existing four) so future recall can filter analogues vs lived experience.
- `retain_incident` keeps its signature; add a thin guard that refuses to
  retain simulator records with `learning.suitable_for_hindsight=False`
  unless explicitly overridden (RCAEval records bypass the gate — they are
  curated ground truth, not agent episodes).

Recall side is unchanged (`text/score/metadata`); the agent parses the
sectioned text back into evidence vs conclusions using the fixed headings.

## 9. Backward compatibility considerations

- **No breaking change:** every new field is optional; `Incident` keeps its
  name, all current fields, defaults, and helper signatures. `SAMPLE_INCIDENT`,
  `memory.py`, `dependencies.py`, and `tests/test_hindsight.py` pass unmodified.
- **`data/rcaeval/processed/incidents.jsonl` is untouched.** No dataset
  migration: a small loader (`rcaeval_record_to_incident()`, to be written
  at implementation time) maps `column_summary → metric_summaries`,
  `excerpts → logs + evidence`, `root_cause → hypotheses[0](confirmed)`,
  and leaves investigation/actions/verification/learning empty. The JSONL
  file itself never needs fake values added.
- **Legacy text fields stay:** `symptoms/logs/actions_taken/resolution/
  lesson` remain populated alongside the structured sections during a
  transition period; the v1 `to_memory_text()` output is a prefix of the v2
  rendering, so existing memories stay comparable.
- **Risk:** `metrics: dict[str,str]` vs numeric summaries — keep the old
  field (stringified snapshot for the text renderer) while analytics use
  `metric_summaries`. Do not "fix" the old field's type; that would break
  the sample/tests for zero benefit.

## 10. Recommended implementation order

1. **Submodels + optional fields** in `backend/app/models/incident.py`
   (this design, verbatim) — no behavior change; run existing tests green.
2. **Helper extensions**: sectioned `to_memory_text()`, enriched context/
   metadata (+ `source`, `fault_type`); keep signatures.
3. **RCAEval loader** `rcaeval_record_to_incident()` (new file, e.g.
   `backend/app/services/rcaeval_loader.py`) mapping §5; round-trip test:
   all 24 JSONL records → `Incident` → validation passes, agent sections empty.
4. **Retain-path update** in `hindsight_service.py`: conditional sections +
   the `suitable_for_hindsight` gate + `"Remediation: not recorded"` line.
   Recall path untouched.
5. **Simulator contract first** (Pydantic-only, no simulator code): a
   `simulator_episode_to_incident()` stub signature the future simulator
   must satisfy, mirroring §6–§7.
6. Only then: simulator, agent loop, recall-filtering by `source`.

Explicitly out of scope for steps 1–4: any scoring/ranking system, any new
API routes, any Hindsight SDK changes, any simulator/agent code.

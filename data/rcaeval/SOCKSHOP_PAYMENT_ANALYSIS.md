# Sock Shop / Payment Analysis of the RCAEval Selection

Inspection-only analysis of the existing 24-case selection
(`data/rcaeval/processed/incidents.jsonl`, `data/rcaeval/selected_cases.csv`,
raw parquet under `data/rcaeval/selected/`). Nothing was downloaded,
modified, or synthesized for this report. All claims below are grounded in
those files; counts and samples were computed 2026-09-28.

## 1. Executive summary

- **None of the 6 Sock Shop (RE2-SS) cases injects a fault into the
  `payment` service.** Root causes are `catalogue` (cpu, delay), `orders`
  (disk), and `user` (loss, mem, socket).
- `payment` exists in Sock Shop only as a *monitored bystander*: 6 metric
  series per case, ~1.8–2.4k routine log lines per case, **zero error-like
  payment log lines in all 6 cases**, and negligible metric shifts.
- **No RE2-SS case has traces** (true for all of Sock Shop in RCAEval, not a
  selection gap).
- Recommendation: **(A) Historical SRE diagnostic memory — not (B) direct
  payment-api training data.** The Sock Shop cases are useful as
  cross-service fault-propagation analogues; the payment-api simulator must
  still be built to produce payment-specific experience.

## 2. All 6 Sock Shop cases

| # | Case ID | Root-cause service | Fault | Rep | Inject (UTC) | Metrics | Logs | Traces | Top post-injection indicators |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `re2ss_catalogue_cpu_2` | catalogue | cpu | 2 | 2024-01-19T20:57:53 | 75 × 1441 steps | 74,548 (43,098 post) | none | catalogue_diskio, catalogue_cpu, catalogue_mem, catalogue_latency-90 |
| 2 | `re2ss_catalogue_delay_3` | catalogue | delay | 3 | 2024-01-20T00:47:04 | 76 × 1441 steps | 78,812 (35,635 post) | none | rabbitmq_diskio, front-end_error, catalogue_latency-90/50 |
| 3 | `re2ss_orders_disk_1` | orders | disk | 1 | 2024-01-21T07:32:31 | 79 × 1441 steps | 70,374 (27,075 post) | none | catalogue-db_diskio, orders_diskio, rabbitmq_diskio, orders_error, front-end_error |
| 4 | `re2ss_user_loss_1` | user | loss | 1 | 2024-01-18T22:21:00 | 79 × 1441 steps | 53,507 (9,847 post) | none | front-end_error, orders_error, user_latency-90/50 |
| 5 | `re2ss_user_mem_3` | user | mem | 3 | 2024-01-20T20:50:25 | 74 × 1441 steps | 85,809 (42,737 post) | none | user_diskio, user_mem, user_cpu, user_latency-90 |
| 6 | `re2ss_user_socket_1` | user | socket | 1 | 2024-01-19T08:57:16 | 82 × 1441 steps | 84,250 (41,853 post) | none | carts_error, user_latency-90/50, user_mem, user_socket |

Per-case detail:

- **re2ss_catalogue_cpu_2** — CPU stress in catalogue. Own-service signal is
  clean (cpu/mem/diskio/latency-90 all top-ranked). Payment: workload
  1.40→2.05, latency flat. Logs dominated by `queue-master` DockerSpawner
  `AFUNIXSocketException` errors at injection time (harness infra noise —
  see §6).
- **re2ss_catalogue_delay_3** — network delay in catalogue. Fault propagates
  to `front-end_error` (top-2 indicator) and downstream latencies; payment
  metrics move slightly *down* (workload 2.02→1.69). Good blast-radius example.
- **re2ss_orders_disk_1** — disk stress in orders. `orders_diskio` +
  `orders_error` + `front-end_error` top-ranked; widest container spread in
  logs (15 containers incl. rabbitmq, catalogue-db). Payment flat.
- **re2ss_user_loss_1** — packet loss in user. Strongest cross-service
  signature in the SS set: `front-end_error` and `orders_error` lead the
  indicators, and **payment_workload collapses 2.03→0.36** — the clearest
  payment-as-downstream-victim observation in the data. `payment_error`
  column exists but stays all-zero. Logs show zipkin
  `UnknownHostException` span drops (observability-pipeline side effect).
- **re2ss_user_mem_3** — memory stress in user. Tightest own-service
  signature (user_diskio/mem/cpu top-3). Payment essentially unchanged.
- **re2ss_user_socket_1** — socket pressure in user. Only SS case with a
  `payment_diskio` column (all zeros); `payment_error` column present, all
  zeros. Notable: `carts_error` is the #1 indicator — cross-service error
  propagation without a local error counter firing.

Log-pattern note: in 5/6 cases the deterministic excerpts are dominated by
`queue-master` spawner I/O exceptions timestamped at injection. They
coincide with faults but originate in the benchmark harness (unix-socket
Docker spawner), so they must not be taught as application diagnostics.

## 3. Payment-service findings

1. **Are any of the 6 Sock Shop cases for the `payment` service? No.**
   Not a single one: 2 × catalogue, 1 × orders, 3 × user.
2. Exact payment case IDs: **none exist** in the selection (and the
   RE2-SS suite offers none — its injectable services are catalogue,
   orders, user; payment is never a root-cause service).
3. Fault types affecting payment: **none injected**; only sympathetic
   movement, strongest being the workload collapse in `re2ss_user_loss_1`.
4. Telemetry available *about* payment in each SS case:
   - Metrics: `payment_cpu`, `payment_mem`, `payment_socket`,
     `payment_workload`, `payment_latency-50`, `payment_latency-90`
     (+ `payment_error` in 2/6 cases, all zeros; `payment_diskio` in 1/6,
     all zeros). All deltas negligible except the loss-case workload drop.
   - Logs: 1,810–2,418 lines per case, exclusively routine
     `Health result=1` / `Authorise result=true` lines — **0 error-like
     lines in all 6 cases** (verified by keyword scan over the raw parquet).
   - Traces: none (Sock Shop has no traces in RCAEval at all).
5. Useful as historical diagnostic experience? **Partially.** They teach
   fault-type signatures (what cpu/mem/loss/socket look like in metrics)
   and cross-service propagation (frontend/carts/orders errors firing for a
   user/catalogue fault). They teach nothing about diagnosing a sick
   payment service itself.
6. What they do NOT contain: a payment root cause; any payment anomaly;
   any payment error log; traces touching payment; remediation actions;
   recovery/verification signals; postmortem lessons.

## 4. Telemetry comparison: planned payment-api signals vs RCAEval Sock Shop

| Signal | Present in RCAEval SS? | Source case(s) | Useful for OPSYN? | Notes |
|---|---|---|---|---|
| CPU | Yes | all 6 (`payment_cpu`, plus per-service `*_cpu`) | Yes | Direct analogue; own-service cpu ranks top for cpu faults |
| Memory | Yes | all 6 (`payment_mem`, `*_mem`) | Yes | Same shape as planned signal |
| Database connections | No | — | No | No `*conn*` metric column exists in SS |
| Database latency | No | — | No | Only service latency-50/90; no DB-breakdown series |
| Redis health | No (in SS) | — | Partially | No redis in Sock Shop; RE2-OB has `redis_cpu`/`redis_mem` — closest cache-health proxy |
| Request rate | Partial | all 6 (`*_workload` series) | Partial | Throughput proxy, not a true request-rate counter |
| HTTP 5xx rate | No | — | No | Only sparse `*_error` counters (`payment_error` in 2/6 cases, all zeros); no status-code rates |
| P95/P99 latency | Partial | all 6 (`*_latency-50`, `*_latency-90`) | Partial | p50/p90 only; no p95/p99 |
| Dependency latency | No | — | No | Would need traces; SS has none |
| Queue depth | No | — | No | `queue-master_*` columns are resource usage of a service literally named queue-master, not a depth gauge |
| Deployment status | No | — | No | No deploy/version/restarts signal anywhere in RCAEval |

Score: 2 full / 3 partial / 6 missing for the payment-api design. The
missing six (DB connections/latency, 5xx rate, dependency latency, queue
depth, deploy status) are exactly what the simulator must generate.

## 5. What RCAEval can teach our agent

- Fault-type metric signatures: cpu→cpu saturation + latency rise; mem→mem
  growth; loss→error counters + downstream latency; socket→socket pressure
  (each verified in the top-indicator rankings above).
- Blast-radius reasoning: `front-end_error`/`orders_error`/`carts_error`
  firing for faults injected elsewhere; the `re2ss_user_loss_1`
  payment-workload collapse as a downstream-victim pattern.
- Log triage priors: error-keyword density by container post-injection;
  distinguishing app errors from harness noise (queue-master/zipkin).
- Metric-shape literacy over 74–82 series × 1441 timesteps per case —
  realistic volume for recall-then-reason loops.

## 6. What RCAEval cannot teach our agent

- Diagnosing a failing payment service (no payment root cause, no payment
  anomaly, zero payment error logs in the SS set).
- Anything involving traces for Sock Shop (none exist).
- Remediation: no actions taken, failed or successful — nothing to imitate.
- Recovery verification: no post-fix time windows or health confirmations.
- Postmortem lessons: no lesson/impact fields exist (our normalized
  records carry them as explicit nulls, never invented).
- Harness-noise caution: queue-master DockerSpawner exceptions and zipkin
  drops coincide with injections but are benchmark scaffolding, not
  application evidence.

## 7. Recommended role in OPSYN

**A. Historical SRE diagnostic memory.**

Reasoning from the evidence: the SS cases supply genuine fault signatures
and propagation patterns worth recalling (§5), but zero payment-specific
diagnostic experience (§3) and zero response knowledge of any kind (§6).
That rules out **B** (nothing payment-specific to train on) and therefore
**C**; **D** would discard real, verified diagnostic signal for no reason.
Concretely: seed Hindsight with these 24 incidents as *analogue memory*
("this cpu-saturation shape resembled re2ss_catalogue_cpu_2"), and let the
payment-api simulator produce the *payment-specific* memory the agent will
actually reason over during incidents.

## 8. Exact next step

Build the `payment-api` simulator emitting the §4 signal set (CPU, memory,
DB connections, DB latency, Redis health, request rate, 5xx rate, p95/p99,
dependency latency, queue depth, deployment status) across fault scenarios
mirroring the six RE2 fault types — then retain simulator runs as new
Hindsight experiences alongside (not instead of) these RCAEval analogues.
Simulator fault labels should reuse RCAEval's vocabulary
(cpu/mem/disk/delay/loss/socket) so recall can bridge both memories.

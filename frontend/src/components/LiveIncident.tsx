import { useEffect, useMemo, useRef, useState } from "react"
import {
  createIncident,
  getIncident,
  getLogs,
  getSnapshot,
  recallMemories,
  resetSystem,
  runAgent,
  type AgentRunResult,
  type Hypothesis,
  type Memory,
  type MetricSnapshot,
  type Scenario,
  type Snapshot,
  type SystemState,
} from "../lib/api"
import { Card, Dot, Fact, RiskTag, SectionLabel, SignalMeter, SignalPill } from "./ui"

/* ------------------------- presentation contracts ------------------------ */
// These mirror the backend's stable tool/hypothesis vocabulary so the UI can
// label actions operationally. No incident data is hardcoded here — every
// value rendered comes from a live backend response.

const ACTION_LABELS: Record<string, string> = {
  rollback_deployment: "Roll back deployment",
  restart_service: "Restart payment service",
  clear_db_connections: "Clear DB connections",
  restart_redis: "Restart Redis cache",
  restore_dependency: "Restore downstream dependency",
  scale_service: "Scale service capacity",
  clear_queue: "Drain request queue",
  free_disk: "Reclaim disk space",
}

const ACTION_RISK: Record<string, "Low" | "Medium" | "High"> = {
  rollback_deployment: "Medium",
  restart_service: "Medium",
  clear_db_connections: "Low",
  restart_redis: "Low",
  restore_dependency: "Low",
  scale_service: "Medium",
  clear_queue: "Low",
  free_disk: "Low",
}

const HYPOTHESIS_ACTION: Record<string, string> = {
  "DB pool exhaustion": "clear_db_connections",
  "bad deployment": "rollback_deployment",
  "memory leak": "restart_service",
  "redis failure": "restart_redis",
  "dependency timeout": "restore_dependency",
  "traffic spike": "scale_service",
  "cache stampede": "restart_service",
  "disk exhaustion": "free_disk",
}

const actionLabel = (action: string) => ACTION_LABELS[action] ?? action

/* ------------------------------ formatting -------------------------------- */

function fmtMs(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`
  return `${Math.round(value)} ms`
}

function fmtPct(value: number): string {
  return `${value}%`
}

function num(value: number | string | undefined): number | null {
  if (typeof value === "number") return value
  if (typeof value === "string") {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

type Tone = "critical" | "good" | "neutral"

function toneOf(abnormal: boolean, healthy: boolean): Tone {
  if (abnormal) return "critical"
  if (healthy) return "good"
  return "neutral"
}

/* --------------------------------- stages --------------------------------- */

type Stage =
  | "observing"
  | "remembering"
  | "comparing"
  | "reasoning"
  | "deciding"
  | "acting"
  | "verifying"
  | "resolved"
  | "learning"

const STAGE_LABELS: { stage: Stage; label: string }[] = [
  { stage: "observing", label: "Observing current system" },
  { stage: "remembering", label: "Recalling organizational experience" },
  { stage: "comparing", label: "Comparing against previous incidents" },
  { stage: "reasoning", label: "Evaluating possible causes" },
  { stage: "deciding", label: "Selecting safest remediation" },
  { stage: "acting", label: "Executing remediation" },
  { stage: "verifying", label: "Verifying recovery" },
  { stage: "learning", label: "Retaining new experience" },
]

/* --------------------------------- hook ----------------------------------- */

type RunState =
  | { phase: "starting" }
  | { phase: "failed"; error: string }
  | {
      phase: "live"
      incidentId: string
      startedAt: Date
      stage: Stage
      snapshot: Snapshot
      logs: string[]
      memories: Memory[]
      memoryNote: string | null
      agentElapsed: number
      result: AgentRunResult | null
    }

function buildRecallQuery(metrics: MetricSnapshot, state: SystemState): string {
  const parts = ["payment-api production incident"]
  const picks: [string, string][] = [
    ["http_5xx_rate", "5xx"],
    ["db_connections", "db_connections"],
    ["db_latency_ms", "db_latency"],
    ["p95_latency_ms", "p95"],
    ["cpu", "cpu"],
    ["memory", "memory"],
    ["redis_health", "redis"],
    ["dependency_latency_ms", "dependency_latency"],
    ["request_rate", "request_rate"],
    ["queue_depth", "queue"],
    ["disk_utilization", "disk"],
  ]
  for (const [key, label] of picks) {
    const value = metrics[key]
    if (value !== undefined) parts.push(`${label}=${value}`)
  }
  parts.push(`deployment=${state.deployment.version}(${state.deployment.status})`)
  return parts.join(" ")
}

function useLiveRun(scenario: Scenario, sessionKey: number) {
  const [run, setRun] = useState<RunState>({ phase: "starting" })

  useEffect(() => {
    let cancelled = false
    const timers: number[] = []
    const set = (next: RunState) => {
      if (!cancelled) setRun(next)
    }

    const boot = async () => {
      set({ phase: "starting" })
      // Operator step: inject the fault AND open its persistent record.
      // The returned record ID is the single canonical incident ID used
      // everywhere downstream (header, agent run, history).
      let recordId: string
      let recordStartedAt: Date
      try {
        const record = await createIncident(scenario.fault)
        recordId = record.incident_id
        recordStartedAt = new Date(record.created_at)
      } catch (e) {
        set({ phase: "failed", error: e instanceof Error ? e.message : String(e) })
        return
      }
      const now = recordStartedAt
      const incidentId = recordId

      let snapshot: Snapshot
      let logs: string[]
      try {
        snapshot = await getSnapshot()
        const logsResp = await getLogs(50)
        logs = logsResp.logs
      } catch (e) {
        set({ phase: "failed", error: e instanceof Error ? e.message : String(e) })
        return
      }
      if (cancelled) return
      const base = {
        phase: "live" as const,
        incidentId,
        startedAt: now,
        snapshot,
        logs,
        memories: [] as Memory[],
        memoryNote: null as string | null,
        agentElapsed: 0,
        result: null as AgentRunResult | null,
      }
      set({ ...base, stage: "observing" })

      // remembering
      let memories: Memory[] = []
      let memoryNote: string | null = null
      try {
        const recall = await recallMemories(
          buildRecallQuery(snapshot.metrics, snapshot.state),
        )
        memories = recall.memories.slice(0, 3)
      } catch (e) {
        memoryNote =
          e instanceof Error
            ? `Organizational memory is unreachable right now (${e.message}). OPSYN continues on current evidence alone.`
            : "Organizational memory is unreachable right now."
      }
      if (cancelled) return
      set({ ...base, stage: "remembering", memories, memoryNote })

      // reasoning: the full agent loop runs server-side; the UI tracks it live.
      const tickStarted = Date.now()
      const ticker = window.setInterval(() => {
        if (cancelled) return
        setRun((prev) => {
          if (prev.phase !== "live" || prev.result) return prev
          const elapsed = Math.floor((Date.now() - tickStarted) / 1000)
          const sub: Stage =
            elapsed < 8 ? "comparing" : elapsed < 20 ? "reasoning" : "deciding"
          return { ...prev, stage: sub, agentElapsed: elapsed, memories, memoryNote }
        })
      }, 1000)
      timers.push(ticker)

      let result: AgentRunResult
      try {
        // No fault info travels here: the record already exists, so the
        // agent runs against current simulator state and the run is
        // attached to the record server-side.
        result = await runAgent({ incidentRecordId: incidentId })
      } catch (e) {
        window.clearInterval(ticker)
        set({ phase: "failed", error: e instanceof Error ? e.message : String(e) })
        return
      }
      window.clearInterval(ticker)
      if (cancelled) return

      // reveal execution → verification → resolution → learning on real data
      const reveal: Stage[] = ["acting", "verifying", "resolved", "learning"]
      reveal.forEach((stage, i) => {
        timers.push(
          window.setTimeout(() => {
            if (!cancelled) {
              set({
                ...base,
                stage,
                memories,
                memoryNote,
                agentElapsed: Math.floor((Date.now() - tickStarted) / 1000),
                result,
              })
            }
          }, 1400 * (i + 1)),
        )
      })
    }

    void boot()
    return () => {
      cancelled = true
      timers.forEach((t) => {
        window.clearTimeout(t)
        window.clearInterval(t)
      })
    }
  }, [scenario, sessionKey])

  return run
}

/* --------------------------- derived presentations ------------------------ */

type MetricRow = { label: string; value: string; tone: Tone; fill?: number }

function metricGroups(metrics: MetricSnapshot, state: SystemState): {
  title: string
  rows: MetricRow[]
}[] {
  const dbUsed = num(metrics.db_connections) ?? 0
  const dbLimit = num(metrics.db_connection_limit) ?? 100
  const dbRatio = dbLimit > 0 ? dbUsed / dbLimit : 0
  const dbLat = num(metrics.db_latency_ms) ?? 0
  const fivexx = num(metrics.http_5xx_rate) ?? 0
  const cpu = num(metrics.cpu) ?? 0
  const mem = num(metrics.memory) ?? 0
  const disk = num(metrics.disk_utilization) ?? 0
  const queue = num(metrics.queue_depth) ?? 0
  const req = num(metrics.request_rate) ?? 0
  const p50 = num(metrics.p50_latency_ms)
  const p95 = num(metrics.p95_latency_ms)
  const p99 = num(metrics.p99_latency_ms)
  const depLat = num(metrics.dependency_latency_ms)
  const redis = String(metrics.redis_health ?? state.redis.status)
  const justDeployed =
    state.deployment.status === "just_deployed" ||
    state.deployment.version !== "1.4.2"

  return [
    {
      title: "Traffic",
      rows: [
        {
          label: "Request rate",
          value: `${req} req/s`,
          tone: toneOf(req > 500, false),
          fill: Math.min(req / 1500, 1),
        },
        {
          label: "Queue depth",
          value: `${queue}`,
          tone: toneOf(queue > 50, queue <= 10),
          fill: Math.min(queue / 500, 1),
        },
      ],
    },
    {
      title: "Reliability",
      rows: [
        {
          label: "5xx error rate",
          value: fmtPct(fivexx),
          tone: toneOf(fivexx > 1, fivexx < 1),
          fill: Math.min(fivexx / 30, 1),
        },
      ],
    },
    {
      title: "Performance",
      rows: [
        ...(p50 !== null
          ? [{ label: "P50 latency", value: fmtMs(p50), tone: toneOf(p50 > 500, p50 < 200) as Tone }]
          : []),
        ...(p95 !== null
          ? [{ label: "P95 latency", value: fmtMs(p95), tone: toneOf(p95 > 800, p95 < 300) as Tone }]
          : []),
        ...(p99 !== null
          ? [{ label: "P99 latency", value: fmtMs(p99), tone: toneOf(p99 > 1500, p99 < 500) as Tone }]
          : []),
        ...(depLat !== null
          ? [{
              label: "Dependency latency",
              value: fmtMs(depLat),
              tone: toneOf(depLat > 1000, depLat < 200) as Tone,
            }]
          : []),
      ],
    },
    {
      title: "Infrastructure",
      rows: [
        {
          label: "CPU",
          value: fmtPct(cpu),
          tone: toneOf(cpu > 80, cpu < 60),
          fill: cpu / 100,
        },
        {
          label: "Memory",
          value: fmtPct(mem),
          tone: toneOf(mem > 80, mem < 70),
          fill: mem / 100,
        },
        {
          label: "Disk",
          value: fmtPct(disk),
          tone: toneOf(disk > 90, disk < 80),
          fill: disk / 100,
        },
      ],
    },
    {
      title: "Dependencies",
      rows: [
        {
          label: "DB connections",
          value: `${dbUsed} / ${dbLimit}`,
          tone: toneOf(dbRatio >= 0.9, dbRatio < 0.7),
          fill: dbRatio,
        },
        {
          label: "DB latency",
          value: fmtMs(dbLat),
          tone: toneOf(dbLat > 300, dbLat < 100),
        },
        {
          label: "Redis",
          value: redis === "healthy" ? "Healthy" : redis === "degraded" ? "Degraded" : "Unavailable",
          tone: toneOf(redis !== "healthy", redis === "healthy"),
        },
      ],
    },
    {
      title: "Deployment",
      rows: [
        { label: "Version", value: state.deployment.version, tone: "neutral" as Tone },
        {
          label: "Recent deployment",
          value: justDeployed ? `Yes · ${state.deployment.version}` : "No",
          tone: toneOf(justDeployed, !justDeployed),
        },
      ],
    },
  ]
}

type TimelineEvent = { at: string; label: string; tone: Tone }

function buildTimeline(logs: string[], investigating: boolean): TimelineEvent[] {
  const parsed = logs
    .map((line) => {
      const match = line.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})/)
      const text = line.replace(/^\S+\s+/, "").slice(0, 90)
      return { at: match ? Date.parse(match[1]) : NaN, text, raw: line }
    })
    .filter((e) => !Number.isNaN(e.at))
  if (parsed.length === 0) {
    return investigating
      ? [{ at: "NOW", label: "OPSYN begins investigation", tone: "neutral" }]
      : []
  }
  const latest = Math.max(...parsed.map((e) => e.at))
  const rel = (at: number) => {
    const s = Math.max(0, Math.round((latest - at) / 1000))
    return s === 0 ? "NOW" : `T−${s}s`
  }
  const significant = parsed.filter((e) =>
    /ERROR|WARN|fault|saturat|degrad|exceed|timeout|deploy|restart|recover|drain|reclaim|rollback|action/i.test(
      e.raw,
    ),
  )
  const picked = significant.slice(-6)
  const events: TimelineEvent[] = []
  const firstSig = significant[0]
  if (firstSig && parsed[0].at < firstSig.at) {
    events.push({ at: rel(parsed[0].at), label: "Normal traffic", tone: "good" })
  }
  for (const e of picked) {
    const tone: Tone = /ERROR/.test(e.raw)
      ? "critical"
      : /WARN|degrad|saturat/.test(e.raw)
        ? "critical"
        : "neutral"
    events.push({ at: rel(e.at), label: e.text, tone })
  }
  if (investigating) {
    events.push({ at: "NOW", label: "OPSYN begins investigation", tone: "neutral" })
  }
  return events
}

function selectedHypothesis(hypotheses: Hypothesis[]): Hypothesis | null {
  return (
    hypotheses.find((h) => h.status === "selected") ??
    hypotheses.find((h) => h.status === "supported") ??
    hypotheses[0] ??
    null
  )
}

/* -------------------------------- component ------------------------------- */

export type SessionStats = { incidents: number; recalled: number; stored: number }

export default function LiveIncident({
  scenario,
  sessionKey,
  sessionStats,
  onRunComplete,
  onSimulateAnother,
  onExit,
}: {
  scenario: Scenario
  sessionKey: number
  sessionStats: SessionStats
  onRunComplete: (incidentId: string, delta: { recalled: number; stored: number }) => void
  onSimulateAnother: () => void
  onExit: () => void
}) {
  const run = useLiveRun(scenario, sessionKey)
  const [logsOpen, setLogsOpen] = useState(false)
  const [expandedMem, setExpandedMem] = useState<number | null>(null)
  // Agent-side recall proof: after the run, read the persistent incident
  // record (written server-side during INVESTIGATING) for the memories the
  // agent itself recalled — ids included, not a frontend boolean.
  const [agentRecall, setAgentRecall] = useState<{ count: number; ids: string[] } | null>(null)
  const reportedRef = useRef(false)
  const liveResult = run.phase === "live" ? run.result : null
  const liveIncidentId = run.phase === "live" ? run.incidentId : null
  useEffect(() => {
    if (!liveResult || !liveIncidentId || reportedRef.current) return
    reportedRef.current = true
    const stored = liveResult.learning?.suitable_for_hindsight ? 1 : 0
    getIncident(liveIncidentId)
      .then((rec) => {
        const ids = Array.isArray(rec.recalled_memory_ids) ? rec.recalled_memory_ids : []
        const count = typeof rec.recalled_memory_count === "number" ? rec.recalled_memory_count : ids.length
        setAgentRecall({ count, ids })
        onRunComplete(liveIncidentId, { recalled: count, stored })
      })
      .catch(() => {
        onRunComplete(liveIncidentId, { recalled: 0, stored })
      })
  }, [liveResult, liveIncidentId, onRunComplete])

  const groups = useMemo(
    () =>
      run.phase === "live"
        ? metricGroups(run.snapshot.metrics, run.snapshot.state)
        : [],
    [run],
  )
  const timeline = useMemo(
    () =>
      run.phase === "live"
        ? buildTimeline(run.logs, true)
        : [],
    [run],
  )

  if (run.phase === "starting") {
    return (
      <div className="pt-6">
        <Card className="p-8 text-center">
          <SectionLabel accent>Fault injection</SectionLabel>
          <p className="mt-3 text-[15px]" style={{ color: "var(--color-paper-dim)" }}>
            Injecting the fault into the payment environment…
          </p>
        </Card>
      </div>
    )
  }

  if (run.phase === "failed") {
    return (
      <div className="pt-6">
        <Card className="p-8">
          <SectionLabel>Incident failed to start</SectionLabel>
          <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
            {run.error}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onExit}
              className="rounded-lg px-5 py-2.5 text-[13px] font-medium"
              style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
            >
              ← Back to overview
            </button>
            <ResetButton />
          </div>
        </Card>
      </div>
    )
  }

  const { incidentId, startedAt, stage, snapshot, logs, memories, memoryNote, result } =
    run
  const stageIndex = (s: Stage) =>
    ["observing", "remembering", "comparing", "reasoning", "deciding", "acting", "verifying", "resolved", "learning"].indexOf(s)
  const reached = (s: Stage) => stageIndex(stage) >= stageIndex(s)
  const resolved = result?.outcome === "resolved"
  const top = result ? selectedHypothesis(result.hypotheses) : null
  const failedActions = result?.learning?.failed_actions ?? []

  return (
    <div className="flex flex-col gap-4 pt-6">
      {/* ---- header ---- */}
      <Card glow className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          <Dot tone={resolved ? "good" : "critical"} live={!resolved} />
          <SectionLabel accent>🚨 Active incident</SectionLabel>
          <span className="font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
            {incidentId}
          </span>
          <span
            className="ml-auto font-mono text-[11px]"
            style={{ color: "var(--color-paper-ghost)" }}
          >
            {startedAt.toLocaleTimeString()} ·{" "}
            {resolved ? "Resolved" : "Investigating"}
          </span>
        </div>
        <h2
          className="mt-3 font-display text-2xl font-semibold tracking-tight"
          style={{ color: "var(--color-paper)" }}
        >
          Payment API
          <span className="font-normal" style={{ color: "var(--color-paper-dim)" }}>
            {" "}
            — experiencing elevated failures
          </span>
        </h2>
        <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
          Production simulation
        </p>
      </Card>

      {/* ---- current system state ---- */}
      <Card className="p-6">
        <SectionLabel>Current system state</SectionLabel>
        <p className="mt-2 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
          Live values observed from the payment environment — this is everything OPSYN can see.
        </p>
        <div className="mt-5 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((g) => (
            <div key={g.title}>
              <div
                className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em]"
                style={{ color: "var(--color-paper-ghost)" }}
              >
                {g.title}
              </div>
              <div className="flex flex-col gap-3">
                {g.rows.map((row) => (
                  <div key={row.label} className="flex flex-col gap-2">
                    <div className="flex items-baseline justify-between">
                      <span className="flex items-center gap-2 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
                        <Dot tone={row.tone === "neutral" ? "neutral" : row.tone} />
                        {row.label}
                      </span>
                      <span
                        className="tnum font-mono text-sm font-medium"
                        style={{
                          color:
                            row.tone === "critical"
                              ? "var(--color-critical)"
                              : row.tone === "good"
                                ? "var(--color-good)"
                                : "var(--color-paper)",
                        }}
                      >
                        {row.value}
                      </span>
                    </div>
                    {row.fill !== undefined && (
                      <div className="h-[3px] w-full overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                        <div
                          className="bar-fill h-full rounded-full"
                          style={{
                            width: `${Math.max(Math.min(row.fill, 1) * 100, 3)}%`,
                            background:
                              row.tone === "critical"
                                ? "var(--color-critical)"
                                : row.tone === "good"
                                  ? "var(--color-good)"
                                  : "var(--color-paper-faint)",
                            opacity: 0.85,
                          }}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ---- timeline ---- */}
      <Card className="p-6">
        <SectionLabel>Incident timeline</SectionLabel>
        <div className="relative mt-5 flex flex-col gap-1 pl-6">
          <span className="absolute bottom-2 left-[7px] top-2 w-px" style={{ background: "var(--color-line)" }} />
          {timeline.map((e, i) => (
            <div key={`${e.at}-${i}`} className="relative flex items-baseline gap-3 py-1.5">
              <span className="absolute -left-[22px] top-1/2 flex h-3.5 w-3.5 -translate-y-1/2 items-center justify-center rounded-full" style={{ background: "var(--color-ink-950)" }}>
                <span
                  className="h-2 w-2 rounded-full"
                  style={{
                    background:
                      e.tone === "critical"
                        ? "var(--color-critical)"
                        : e.tone === "good"
                          ? "var(--color-good)"
                          : "var(--color-paper-ghost)",
                  }}
                />
              </span>
              <span className="tnum w-14 shrink-0 font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                {e.at}
              </span>
              <span className="text-[13px]" style={{ color: "var(--color-paper-dim)" }}>
                {e.label}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* ---- logs ---- */}
      <Card className="p-6">
        <div className="flex items-center justify-between gap-4">
          <SectionLabel>System logs</SectionLabel>
          <button
            type="button"
            onClick={() => setLogsOpen((o) => !o)}
            aria-expanded={logsOpen}
            className="font-mono text-[11px] uppercase tracking-wider transition-colors"
            style={{ color: "var(--color-accent)" }}
          >
            {logsOpen ? "Hide full logs" : "View full logs"}
          </button>
        </div>
        <div className="mt-4 flex flex-col gap-1.5 rounded-lg border p-4 font-mono text-[12px] leading-relaxed" style={{ borderColor: "var(--color-line)", background: "var(--color-ink-800)" }}>
          {(logsOpen ? logs : logs.slice(-8)).map((line, i) => {
            const critical = /ERROR/.test(line)
            const warn = !critical && /WARN/.test(line)
            return (
              <div key={i} className="break-words" style={{ color: critical ? "var(--color-critical)" : warn ? "var(--color-paper)" : "var(--color-paper-faint)" }}>
                {line}
              </div>
            )
          })}
        </div>
        {!logsOpen && logs.length > 8 && (
          <p className="mt-2 font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
            Showing the 8 most recent lines of {logs.length} — additional evidence for the agent&apos;s reasoning.
          </p>
        )}
      </Card>

      {/* ---- investigation progress ---- */}
      <Card className="p-6">
        <div className="flex items-center justify-between gap-4">
          <SectionLabel accent>OPSYN investigation</SectionLabel>
          {stageIndex(stage) >= stageIndex("comparing") && !result && (
            <span className="tnum font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }} role="status">
              Reasoning live… {run.agentElapsed}s elapsed
            </span>
          )}
        </div>
        <div className="mt-5 grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {STAGE_LABELS.map((t) => {
            const done = stageIndex(stage) > stageIndex(t.stage)
            const now = stage === t.stage && !result
            const state = done || (result && stageIndex(stage) >= stageIndex(t.stage)) ? "done" : now ? "now" : "pending"
            return (
              <div key={t.stage} className="flex items-center gap-3">
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-[9px]"
                  style={{
                    background: state === "done" ? "rgba(99,201,154,0.15)" : "transparent",
                    color: state === "done" ? "var(--color-good)" : state === "now" ? "var(--color-accent)" : "var(--color-paper-ghost)",
                    border: state === "pending" ? "1px solid var(--color-paper-ghost)" : "none",
                  }}
                >
                  {state === "done" ? "✓" : state === "now" ? "●" : ""}
                </span>
                <span
                  className="text-[13px]"
                  style={{
                    color: state === "pending" ? "var(--color-paper-ghost)" : state === "now" ? "var(--color-paper)" : "var(--color-paper-dim)",
                  }}
                >
                  {t.label}
                </span>
              </div>
            )
          })}
        </div>
      </Card>

      {/* ---- hindsight memories ---- */}
      {stageIndex(stage) >= stageIndex("remembering") && (
        <Card className="p-6">
          <div className="mb-1 flex items-center gap-2.5">
            <span className="text-[15px]">🧠</span>
            <SectionLabel accent>OPSYN remembers</SectionLabel>
            <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
              Recalled from Hindsight
            </span>
          </div>
          {memoryNote ? (
            <p className="mt-3 text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
              {memoryNote}
            </p>
          ) : memories.length === 0 ? (
            <p className="mt-3 text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
              No prior experience matched this incident — OPSYN proceeds on current evidence alone, and what it learns will seed future recall.
            </p>
          ) : (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {memories.map((mem, i) => {
                const id = mem.metadata?.incident_id ?? `memory-${i + 1}`
                const text = mem.text ?? ""
                const expanded = expandedMem === i
                const shown = expanded || text.length <= 420 ? text : `${text.slice(0, 420)}…`
                return (
                  <div key={id} className="flex flex-col gap-2.5 rounded-lg border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-ink-800)" }}>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px]" style={{ color: "var(--color-accent)" }}>{id}</span>
                      {mem.score !== null && mem.score !== undefined && (
                        <span className="tnum ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                          relevance {typeof mem.score === "number" ? mem.score.toFixed(2) : mem.score}
                        </span>
                      )}
                    </div>
                    <p className="whitespace-pre-wrap text-[13px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
                      {shown}
                    </p>
                    {text.length > 420 && (
                      <button
                        type="button"
                        onClick={() => setExpandedMem(expanded ? null : i)}
                        aria-expanded={expanded}
                        className="self-start font-mono text-[11px] uppercase tracking-wider"
                        style={{ color: "var(--color-accent)" }}
                      >
                        {expanded ? "Show less" : "Show full memory"}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      )}

      {/* ---- post-result sections ---- */}
      {result && (
        <>
          <ComparisonSection
            result={result}
            snapshot={snapshot}
            memories={memories}
            incidentId={incidentId}
            agentRecall={agentRecall}
          />
          <HypothesesSection hypotheses={result.hypotheses} />
          <DecisionSection result={result} memoryCount={memories.length} />
          <RemediationSection result={result} />
          <ExecutionSection result={result} revealed={reached("verifying")} />
          <VerificationSection result={result} revealed={reached("resolved")} />
          <LearningSection result={result} revealed={reached("learning")} />
          {reached("learning") && (
            <Card className="p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                <div className="flex-1">
                  <SectionLabel accent>Prove that memory matters</SectionLabel>
                  <p className="mt-2 text-[14px]" style={{ color: "var(--color-paper-dim)" }}>
                    Inject another fault. OPSYN will investigate again — this time with this experience retained.
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2.5">
                  <button
                    type="button"
                    onClick={onSimulateAnother}
                    className="rounded-lg px-5 py-2.5 text-[13px] font-medium transition-transform hover:scale-[1.02]"
                    style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
                  >
                    Inject Another Fault →
                  </button>
                  <ResetButton />
                  <button
                    type="button"
                    onClick={onExit}
                    className="rounded-lg border px-5 py-2.5 text-[13px] font-medium transition-colors"
                    style={{ borderColor: "var(--color-line-strong)", color: "var(--color-paper-dim)" }}
                  >
                    Back to overview
                  </button>
                </div>
              </div>
              {sessionStats.incidents > 0 && (
                <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-4" style={{ borderColor: "var(--color-line)" }} role="status">
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-accent)" }}>
                    OPSYN experience · this session
                  </span>
                  <span className="tnum font-mono text-[12px]" style={{ color: "var(--color-paper-dim)" }}>
                    {sessionStats.incidents} incident{sessionStats.incidents === 1 ? "" : "s"} handled
                  </span>
                  <span className="tnum font-mono text-[12px]" style={{ color: "var(--color-paper-dim)" }}>
                    {sessionStats.recalled} experience{sessionStats.recalled === 1 ? "" : "s"} recalled
                  </span>
                  <span className="tnum font-mono text-[12px]" style={{ color: "var(--color-paper-dim)" }}>
                    {sessionStats.stored} stored
                  </span>
                </div>
              )}
              <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--color-paper-ghost)" }}>
                Reset restores system health only — experience retained in Hindsight stays available for the next incident.
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

/* ------------------------------ sub-sections ------------------------------ */

function ResetButton() {
  const [state, setState] = useState<"idle" | "resetting" | "done" | string>("idle")
  const busy = state === "resetting"
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setState("resetting")
          resetSystem()
            .then(() => setState("done"))
            .catch((e: unknown) =>
              setState(e instanceof Error ? e.message : "Reset failed"),
            )
        }}
        className="rounded-lg border px-5 py-2.5 text-[13px] font-medium transition-colors disabled:cursor-wait disabled:opacity-60"
        style={{ borderColor: "var(--color-line-strong)", color: "var(--color-paper-dim)" }}
      >
        {state === "resetting"
          ? "Resetting…"
          : state === "done"
            ? "✓ System healthy"
            : "Reset system"}
      </button>
      {typeof state === "string" && state !== "idle" && state !== "resetting" && state !== "done" && (
        <span className="max-w-[220px] text-[12px]" style={{ color: "var(--color-fail)" }} role="alert">
          {state}
        </span>
      )}
    </span>
  )
}

function statLabel(status: string): { text: string; strong: boolean } {
  if (status === "supported" || status === "selected")
    return { text: "Strong supporting evidence", strong: true }
  if (status === "investigating") return { text: "Insufficient evidence", strong: false }
  if (status === "rejected") return { text: "Weak evidence", strong: false }
  return { text: "Considered", strong: false }
}

function ComparisonSection({
  result,
  snapshot,
  memories,
  incidentId,
  agentRecall,
}: {
  result: AgentRunResult
  snapshot: Snapshot
  memories: Memory[]
  incidentId: string
  agentRecall: { count: number; ids: string[] } | null
}) {
  const top = selectedHypothesis(result.hypotheses)
  const m = snapshot.metrics
  const current: [string, string][] = [
    ["DB connections", `${m.db_connections ?? "?"} / ${m.db_connection_limit ?? "?"}`],
    ["DB latency", typeof m.db_latency_ms === "number" ? fmtMs(m.db_latency_ms) : String(m.db_latency_ms ?? "—")],
    ["5xx errors", typeof m.http_5xx_rate === "number" ? fmtPct(m.http_5xx_rate) : String(m.http_5xx_rate ?? "—")],
    ["Recent deployment", snapshot.state.deployment.status === "just_deployed" ? `Yes · ${snapshot.state.deployment.version}` : "No"],
  ]
  const memory = memories[0]
  return (
    <Card className="p-6">
      <SectionLabel>Experience vs current incident</SectionLabel>
      <div className="mt-5 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-ink-800)" }}>
          <div className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            Previous incident{memory?.metadata?.incident_id ? ` · ${memory.metadata.incident_id}` : ""}
          </div>
          <p className="mt-2 line-clamp-6 whitespace-pre-wrap text-[13px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
            {memory ? memory.text : "No prior experience was recalled for this incident."}
          </p>
        </div>
        <div className="rounded-lg border p-4" style={{ borderColor: "rgba(141,139,246,0.25)", background: "rgba(141,139,246,0.04)" }}>
          <div className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-accent)" }}>
            Current incident
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {current.map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-3">
                <span className="text-[13px]" style={{ color: "var(--color-paper-faint)" }}>{k}</span>
                <span className="tnum font-mono text-[13px]" style={{ color: "var(--color-paper)" }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="mt-4 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
        {memory && top
          ? `Current conditions were weighed against recalled experience before concluding: ${top.statement}.`
          : "OPSYN weighed current evidence on its own — nothing in memory matched closely enough to lean on."}
      </p>
      <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.14em]" style={{ color: "var(--color-paper-ghost)" }}>
        Historical experience is considered alongside current evidence — current observations decide.
      </p>
      {agentRecall && (
        <p className="mt-2 text-[12px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }} role="status">
          {agentRecall.count > 0
            ? `Incident ${incidentId} recalled ${agentRecall.count} prior experience${agentRecall.count === 1 ? "" : "s"}${agentRecall.ids.length > 0 ? `: ${agentRecall.ids.join(", ")}` : ""}.`
            : `Incident ${incidentId} recalled no prior experience — its learning seeds future recall.`}
        </p>
      )}
    </Card>
  )
}

function HypothesesSection({ hypotheses }: { hypotheses: Hypothesis[] }) {
  return (
    <Card className="p-6">
      <SectionLabel>Possible causes</SectionLabel>
      <p className="mt-2 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
        Every explanation OPSYN weighed — including the ones evidence ruled out.
      </p>
      <div className="mt-5 flex flex-col gap-2.5">
        {hypotheses.map((h) => {
          const s = statLabel(h.status)
          return (
            <div
              key={h.statement}
              className="flex flex-col gap-2 rounded-lg border px-4 py-3.5"
              style={{
                borderColor: s.strong ? "rgba(141,139,246,0.28)" : "var(--color-line)",
                background: s.strong ? "rgba(141,139,246,0.05)" : "transparent",
              }}
            >
              <div className="flex items-center gap-3">
                <span className="text-[15px] font-medium" style={{ color: s.strong ? "var(--color-paper)" : "var(--color-paper-dim)" }}>
                  {h.statement}
                </span>
                <span
                  className="ml-auto shrink-0 font-mono text-[11px] uppercase tracking-wider"
                  style={{ color: s.strong ? "var(--color-accent)" : "var(--color-paper-ghost)" }}
                >
                  {s.text}
                </span>
                {h.confidence !== null && h.confidence !== undefined && (
                  <span className="tnum shrink-0 font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                    {h.confidence}
                  </span>
                )}
              </div>
              {h.supporting.slice(0, 3).map((line) => (
                <p key={line} className="text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
                  <span style={{ color: "var(--color-good)" }}>+ </span>{line}
                </p>
              ))}
              {h.contradicting.slice(0, 2).map((line) => (
                <p key={line} className="text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
                  <span style={{ color: "var(--color-fail)" }}>− </span>{line}
                </p>
              ))}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function DecisionSection({
  result,
  memoryCount,
}: {
  result: AgentRunResult
  memoryCount: number
}) {
  const top = selectedHypothesis(result.hypotheses)
  const executed = result.actions[result.actions.length - 1]
  if (!top) return null
  return (
    <Card glow className="p-6">
      <SectionLabel accent>OPSYN&apos;s decision</SectionLabel>
      <div className="mt-3 text-lg font-semibold" style={{ color: "var(--color-paper)" }}>
        {top.statement}
      </div>
      {top.supporting[0] && (
        <p className="mt-2 border-l-2 pl-3 text-[14px] leading-relaxed italic" style={{ borderColor: "var(--color-accent)", color: "var(--color-paper-dim)" }}>
          “{top.supporting.slice(0, 2).join(" ")}”
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <SignalPill>
          {memoryCount} recalled experience{memoryCount === 1 ? "" : "s"}
        </SignalPill>
        {executed && <SignalPill>Decision: {actionLabel(executed.action)}</SignalPill>}
        {failedActions(result).length > 0 && (
          <SignalPill>{failedActions(result).length} approach ruled out by evidence</SignalPill>
        )}
      </div>
    </Card>
  )
}

function failedActions(result: AgentRunResult): string[] {
  return result.learning?.failed_actions ?? []
}

function RemediationSection({ result }: { result: AgentRunResult }) {
  const failed = new Set(failedActions(result))
  const attempted = new Set(result.actions.map((a) => a.action))
  // Alternatives: hypotheses whose mapped action was never attempted.
  const seen = new Set<string>()
  const alternatives: { statement: string; action: string; note: string }[] = []
  for (const h of result.hypotheses) {
    const action = HYPOTHESIS_ACTION[h.statement]
    if (!action || attempted.has(action) || seen.has(action)) continue
    seen.add(action)
    alternatives.push({
      statement: h.statement,
      action,
      note:
        h.status === "rejected"
          ? `Ruled out: ${(h.contradicting[0] ?? "contradicted by current evidence.") as string}`
          : `Not selected: ${(h.supporting[0] ?? "weaker evidence than the chosen path.") as string}`,
    })
    if (alternatives.length >= 2) break
  }
  const actionOutcome = (action: string): "failed" | "success" => {
    if (failed.has(action)) return "failed"
    return "success"
  }
  return (
    <Card className="p-6">
      <SectionLabel>Available remediations</SectionLabel>
      <p className="mt-2 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
        Every remediation OPSYN attempted, in order — including approaches
        the evidence ruled out mid-run.
      </p>
      <div className="mt-5 flex flex-col gap-2.5">
        {result.actions.map((act, i) => {
          const outcome = actionOutcome(act.action)
          const isLast = i === result.actions.length - 1
          return (
            <div key={`${act.action_id}-${i}`} className="flex flex-col gap-2 rounded-lg border px-4 py-3.5" style={{ borderColor: outcome === "failed" ? "rgba(224,132,151,0.3)" : "rgba(141,139,246,0.28)", background: outcome === "failed" ? "transparent" : "rgba(141,139,246,0.05)" }}>
              <div className="flex items-center gap-3">
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-[10px]"
                  style={{
                    background: outcome === "failed" ? "rgba(224,132,151,0.14)" : "rgba(99,201,154,0.14)",
                    color: outcome === "failed" ? "var(--color-fail)" : "var(--color-good)",
                  }}
                >
                  {outcome === "failed" ? "✗" : "✓"}
                </span>
                <span className="text-[15px] font-medium" style={{ color: "var(--color-paper)" }}>
                  {actionLabel(act.action)}
                </span>
                <span className="rounded-md px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider" style={{ background: outcome === "failed" ? "rgba(224,132,151,0.14)" : "rgba(141,139,246,0.16)", color: outcome === "failed" ? "var(--color-fail)" : "var(--color-accent)" }}>
                  {outcome === "failed" ? "No significant change" : isLast ? "Selected · recovered" : "Attempted"}
                </span>
                <span className="ml-auto"><RiskTag risk={ACTION_RISK[act.action] ?? "Low"} /></span>
              </div>
              <p className="text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
                {act.result ?? "Executed against the payment environment."}
              </p>
            </div>
          )
        })}
        {alternatives.map((a) => (
          <div key={a.action} className="flex flex-col gap-2 rounded-lg border px-4 py-3.5" style={{ borderColor: "var(--color-line)" }}>
            <div className="flex items-center gap-3">
              <span className="text-[15px] font-medium" style={{ color: "var(--color-paper-dim)" }}>
                {actionLabel(a.action)}
              </span>
              <span className="rounded-md px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider" style={{ background: "var(--color-hover-wash)", color: "var(--color-paper-ghost)" }}>
                Not attempted
              </span>
              <span className="ml-auto"><RiskTag risk={ACTION_RISK[a.action] ?? "Low"} /></span>
            </div>
            <p className="text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
              Considered for “{a.statement}”. {a.note}
            </p>
          </div>
        ))}
        {failed.size > 0 && (
          <p className="text-[12px]" style={{ color: "var(--color-paper-ghost)" }}>
            Ruled out by evidence during this run: {[...failed].map(actionLabel).join(", ")} — recorded as failed actions in the retained experience.
          </p>
        )}
      </div>
    </Card>
  )
}

function ExecutionSection({
  result,
  revealed,
}: {
  result: AgentRunResult
  revealed: boolean
}) {
  const failed = new Set(failedActions(result))
  if (result.actions.length === 0) return null
  return (
    <Card className="p-6">
      <SectionLabel accent>Executing remediation</SectionLabel>
      <div className="mt-4 flex flex-col gap-5">
        {result.actions.map((act, i) => {
          const wasFailure = failed.has(act.action)
          return (
            <div key={`${act.action_id}-${i}`}>
              <div className="flex items-center gap-2 text-[15px] font-medium" style={{ color: "var(--color-paper)" }}>
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-[10px]"
                  style={{
                    background: wasFailure ? "rgba(224,132,151,0.14)" : "rgba(99,201,154,0.14)",
                    color: wasFailure ? "var(--color-fail)" : "var(--color-good)",
                  }}
                >
                  {wasFailure ? "✗" : "✓"}
                </span>
                {actionLabel(act.action)}
                <span className="tnum ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                  attempt {i + 1} of {result.actions.length}
                  {wasFailure ? " · no significant change" : ""}
                </span>
              </div>
              <div className="mt-3">
                <div className="relative h-[3px] w-full overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                  {!revealed && <div className="sweep absolute inset-0" />}
                  <div
                    className="bar-fill h-full rounded-full"
                    style={{
                      width: revealed ? "100%" : "62%",
                      background: wasFailure ? "var(--color-fail)" : revealed ? "var(--color-good)" : "var(--color-accent)",
                    }}
                  />
                </div>
                <div className="mt-2 flex justify-between">
                  {["Preparing", "Executing", wasFailure ? "No change" : "Completed"].map((s, j) => {
                    const on = revealed ? true : j <= 1
                    return (
                      <span
                        key={s}
                        className="font-mono text-[11px] uppercase tracking-wider"
                        style={{
                          color: revealed && j === 2 ? (wasFailure ? "var(--color-fail)" : "var(--color-good)") : on ? "var(--color-paper-dim)" : "var(--color-paper-ghost)",
                        }}
                      >
                        {s}
                      </span>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function VerificationSection({
  result,
  revealed,
}: {
  result: AgentRunResult
  revealed: boolean
}) {
  const v = result.verification
  if (!v) return null
  const rows: [string, number | undefined, number | undefined][] = [
    ["5xx errors", v.metrics_before.http_5xx_rate, v.metrics_after.http_5xx_rate],
    ["P95 latency", v.metrics_before.p95_latency_ms, v.metrics_after.p95_latency_ms],
    ["DB connections", v.metrics_before.db_connections, v.metrics_after.db_connections],
    ["Queue depth", v.metrics_before.queue_depth, v.metrics_after.queue_depth],
  ]
  const resolved = result.outcome === "resolved"
  return (
    <Card className="p-6">
      <SectionLabel>Verifying recovery</SectionLabel>
      <p className="mt-2 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
        OPSYN re-observed the environment after acting — recovery is measured, never assumed.
      </p>
      <div className="mt-5 grid gap-6 sm:grid-cols-2">
        {(["Before", "After"] as const).map((title, col) => (
          <div key={title}>
            <div
              className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em]"
              style={{ color: col === 0 ? "var(--color-paper-ghost)" : revealed && resolved ? "var(--color-good)" : "var(--color-paper-ghost)" }}
            >
              {title}
            </div>
            <div className="flex flex-col gap-3">
              {rows.map(([label, before, after]) => {
                const value = col === 0 ? before : after
                const shown =
                  value === undefined
                    ? "—"
                    : label === "5xx errors"
                      ? fmtPct(value)
                      : label === "P95 latency"
                        ? fmtMs(value)
                        : `${value}`
                return (
                  <div key={label} className="flex items-baseline justify-between border-b pb-2.5" style={{ borderColor: "var(--color-line)" }}>
                    <span className="text-[13px]" style={{ color: "var(--color-paper-faint)" }}>{label}</span>
                    <span
                      className="tnum font-mono text-[14px]"
                      style={{ color: col === 0 ? "var(--color-paper-faint)" : revealed ? "var(--color-good)" : "var(--color-paper-ghost)" }}
                    >
                      {revealed || col === 0 ? shown : "···"}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
      {revealed && (
        <div
          className="rise mt-5 flex items-center gap-3 rounded-xl border px-6 py-5"
          role="status"
          style={{
            borderColor: resolved ? "rgba(99,201,154,0.28)" : "rgba(240,163,94,0.3)",
            background: resolved ? "rgba(99,201,154,0.06)" : "rgba(240,163,94,0.05)",
          }}
        >
          <Dot tone={resolved ? "good" : "critical"} />
          <div>
            <div className="font-display text-lg font-semibold" style={{ color: "var(--color-paper)" }}>
              {resolved ? "Incident resolved" : `Incident ${result.outcome ?? "unresolved"}`}
            </div>
            <div className="text-[14px]" style={{ color: "var(--color-paper-dim)" }}>
              {resolved
                ? "Payment API recovered and verification completed."
                : "OPSYN could not verify recovery — the trace above shows everything it tried."}
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}

function LearningSection({
  result,
  revealed,
}: {
  result: AgentRunResult
  revealed: boolean
}) {
  const learning = result.learning
  if (!learning) return null
  const notWorked = learning.failed_actions ?? []
  return (
    <Card glow className="p-6">
      <div className="flex items-center gap-2.5">
        <span className="text-[15px]">🧠</span>
        <SectionLabel accent>Experience retained</SectionLabel>
      </div>
      <div className="mt-5 grid gap-5 md:grid-cols-3">
        <LearnCell label="What happened" value={learning.lesson ?? "Investigation completed."} />
        <LearnCell
          label="What worked"
          value={
            learning.successful_actions.length > 0
              ? learning.successful_actions.map(actionLabel).join(", ")
              : "No remediation verified — the attempt history itself was retained."
          }
        />
        {notWorked.length > 0 ? (
          <LearnCell
            label="What didn't work"
            value={`${notWorked.map(actionLabel).join(", ")} — recorded so future incidents don't repeat it blindly.`}
          />
        ) : (
          <LearnCell
            label="Observed outcome"
            value={learning.outcome === "resolved" ? "Recovery verified." : `Ended ${learning.outcome ?? "without resolution"}.`}
          />
        )}
      </div>
      {revealed && (
        <div className="mt-4 flex items-center gap-2 text-[12px]" style={{ color: "var(--color-good)" }}>
          <Dot tone="good" />
          {learning.suitable_for_hindsight
            ? "Saved to organizational memory"
            : "Kept locally for this session"}
          <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            Powered by Hindsight
          </span>
        </div>
      )}
    </Card>
  )
}

function LearnCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>
        {label}
      </div>
      <div className="mt-1 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
        {value}
      </div>
    </div>
  )
}

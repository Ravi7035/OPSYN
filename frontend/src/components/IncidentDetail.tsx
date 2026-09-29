import { useEffect, useState } from "react"
import { getIncident, type Hypothesis, type IncidentRecord } from "../lib/api"
import { formatDuration } from "./pages"
import { Card, Dot, SectionLabel, SignalPill } from "./ui"

const LIFECYCLE = ["INJECTED", "INVESTIGATING", "REMEDIATING", "VERIFYING"] as const

const ACTION_LABELS: Record<string, string> = {
  rollback_deployment: "Rollback deployment",
  restart_service: "Restart payment service",
  clear_db_connections: "Clear DB connections",
  restart_redis: "Restart Redis cache",
  restore_dependency: "Restore downstream dependency",
  scale_service: "Scale service capacity",
  clear_queue: "Drain request queue",
  free_disk: "Reclaim disk space",
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

function statusTone(status: string): "critical" | "good" | "neutral" {
  if (status === "RESOLVED") return "good"
  if (status === "FAILED") return "critical"
  return "neutral"
}

/**
 * Read-only history of one persisted incident. Everything rendered comes
 * from GET /api/incidents/{id} — the stored agent trace, never invented.
 */
export default function IncidentDetail({
  recordId,
  onBack,
  onSimulate,
}: {
  recordId: string
  onBack: () => void
  onSimulate: () => void
}) {
  const [record, setRecord] = useState<IncidentRecord | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    getIncident(recordId)
      .then((r) => live && setRecord(r))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [recordId])

  if (error !== null) {
    return (
      <div className="pt-6">
        <Card className="p-6">
          <SectionLabel>Incident unavailable</SectionLabel>
          <p className="mt-2 text-[14px]" style={{ color: "var(--color-paper-dim)" }}>
            {error}
          </p>
          <BackButton onBack={onBack} />
        </Card>
      </div>
    )
  }

  if (record === null) {
    return (
      <div className="pt-6">
        <Card className="p-6">
          <p className="text-[14px]" style={{ color: "var(--color-paper-faint)" }}>
            Loading incident {recordId}…
          </p>
        </Card>
      </div>
    )
  }

  const reachedStages = new Set(record.stage_history.map((s) => s.stage))
  const stageAt = (stage: string) =>
    record.stage_history.find((s) => s.stage === stage)?.at ?? null
  const terminal = ["RESOLVED", "FAILED", "UNRESOLVED"].includes(record.status)
  const hypotheses = record.trace.hypotheses ?? []
  const actions = record.trace.actions ?? []
  const verification = record.trace.verification ?? null
  const learning = record.trace.learning ?? null
  const investigation = record.trace.investigation ?? []

  return (
    <div className="flex flex-col gap-4 pt-6">
      <button
        type="button"
        onClick={onBack}
        className="self-start font-mono text-[11px] uppercase tracking-wider transition-colors"
        style={{ color: "var(--color-paper-faint)" }}
      >
        ← All incidents
      </button>

      {/* ---- header ---- */}
      <Card glow className="p-6">
        <div className="flex flex-wrap items-center gap-3">
          <Dot tone={statusTone(record.status)} live={!terminal} />
          <SectionLabel accent>
            {record.status === "RESOLVED"
              ? "Incident resolved"
              : terminal
                ? `Incident ${record.status.toLowerCase()}`
                : "Incident in progress"}
          </SectionLabel>
          <span className="font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
            {record.incident_id}
          </span>
          <span className="ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
            {formatDuration(record.created_at, record.resolved_at)}
            {record.resolved_at ? "" : " so far"}
          </span>
        </div>
        <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>
          {record.title}
        </h2>
        <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
          {record.service} · production simulation
        </p>
      </Card>

      {/* ---- lifecycle ---- */}
      <Card className="p-6">
        <SectionLabel>Lifecycle</SectionLabel>
        <div className="mt-5 grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {LIFECYCLE.map((stage) => {
            const done = reachedStages.has(stage)
            const at = stageAt(stage)
            return (
              <div key={stage} className="flex items-center gap-3">
                <span
                  className="flex h-4 w-4 items-center justify-center rounded-full text-[9px]"
                  style={{
                    background: done ? "rgba(99,201,154,0.15)" : "transparent",
                    color: done ? "var(--color-good)" : "var(--color-paper-ghost)",
                    border: done ? "none" : "1px solid var(--color-paper-ghost)",
                  }}
                >
                  {done ? "✓" : ""}
                </span>
                <span className="text-[13px]" style={{ color: done ? "var(--color-paper-dim)" : "var(--color-paper-ghost)" }}>
                  {stage.charAt(0) + stage.slice(1).toLowerCase()}
                </span>
                {at && (
                  <span className="tnum ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                    {new Date(at).toLocaleTimeString()}
                  </span>
                )}
              </div>
            )
          })}
          <div className="flex items-center gap-3">
            <span
              className="flex h-4 w-4 items-center justify-center rounded-full text-[9px]"
              style={{
                background: terminal ? "rgba(99,201,154,0.15)" : "transparent",
                color: terminal ? "var(--color-good)" : "var(--color-paper-ghost)",
                border: terminal ? "none" : "1px solid var(--color-paper-ghost)",
              }}
            >
              {terminal ? "✓" : ""}
            </span>
            <span className="text-[13px]" style={{ color: terminal ? "var(--color-paper-dim)" : "var(--color-paper-ghost)" }}>
              {record.status.charAt(0) + record.status.slice(1).toLowerCase()}
            </span>
            {record.resolved_at && (
              <span className="tnum ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                {new Date(record.resolved_at).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* ---- loop summary ---- */}
      <Card className="p-6">
        <SectionLabel>Observe → Recall → Reason → Act → Verify → Learn</SectionLabel>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <LoopCell k="Observed signals" v={`${record.detected_symptoms.length} recorded`} />
          <LoopCell
            k="Recalled experience"
            v={
              record.recalled_memory_count > 0
                ? `${record.recalled_memory_count} memor${record.recalled_memory_count === 1 ? "y" : "ies"}`
                : "None matched"
            }
          />
          <LoopCell k="Hypotheses weighed" v={`${hypotheses.length}`} />
          <LoopCell k="Actions executed" v={`${actions.length}`} />
          <LoopCell
            k="Verification"
            v={
              verification?.improved === true
                ? "Recovery verified"
                : verification?.improved === false
                  ? "No improvement"
                  : "—"
            }
          />
          <LoopCell
            k="Learning"
            v={record.suitable_for_hindsight ? "Retained in memory" : "Not retained"}
          />
        </div>
        {record.detected_symptoms.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {record.detected_symptoms.slice(0, 10).map((s) => (
              <SignalPill key={s}>{s}</SignalPill>
            ))}
          </div>
        )}
      </Card>

      {/* ---- hypotheses ---- */}
      {hypotheses.length > 0 && (
        <Card className="p-6">
          <SectionLabel>Possible causes weighed</SectionLabel>
          <div className="mt-4 flex flex-col gap-2.5">
            {hypotheses.map((h: Hypothesis) => (
              <div key={h.statement} className="rounded-lg border px-4 py-3" style={{ borderColor: "var(--color-line)" }}>
                <div className="flex items-center gap-3">
                  <span className="text-[14px] font-medium" style={{ color: "var(--color-paper-dim)" }}>
                    {h.statement}
                  </span>
                  <span className="ml-auto shrink-0 font-mono text-[11px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>
                    {h.status}
                    {h.confidence !== null && h.confidence !== undefined ? ` · ${h.confidence}` : ""}
                  </span>
                </div>
                {(h.supporting ?? []).slice(0, 2).map((line) => (
                  <p key={line} className="mt-1 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
                    <span style={{ color: "var(--color-good)" }}>+ </span>{line}
                  </p>
                ))}
                {(h.contradicting ?? []).slice(0, 2).map((line) => (
                  <p key={line} className="mt-1 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
                    <span style={{ color: "var(--color-fail)" }}>− </span>{line}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ---- actions + verification ---- */}
      {actions.length > 0 && (
        <Card className="p-6">
          <SectionLabel>Remediation & verification</SectionLabel>
          <div className="mt-4 flex flex-col gap-2.5">
            {actions.map((a) => (
              <div key={a.action_id} className="rounded-lg border px-4 py-3" style={{ borderColor: "var(--color-line)" }}>
                <div className="text-[14px] font-medium" style={{ color: "var(--color-paper)" }}>
                  {actionLabel(a.action)}
                </div>
                {a.result && (
                  <p className="tnum mt-1 font-mono text-[12px]" style={{ color: "var(--color-paper-faint)" }}>
                    {a.result}
                  </p>
                )}
              </div>
            ))}
          </div>
          {verification && (
            <p className="mt-4 text-[13px]" style={{ color: "var(--color-paper-dim)" }}>
              Verification:{" "}
              <span style={{ color: verification.improved ? "var(--color-good)" : "var(--color-paper)" }}>
                {verification.improved ? "improved" : "no improvement"}
              </span>{" "}
              <span className="tnum font-mono text-[12px]" style={{ color: "var(--color-paper-faint)" }}>
                (5xx {verification.metrics_before?.http_5xx_rate ?? "—"} →{" "}
                {verification.metrics_after?.http_5xx_rate ?? "—"})
              </span>
            </p>
          )}
        </Card>
      )}

      {/* ---- learning ---- */}
      {learning && (
        <Card glow className="p-6">
          <div className="flex items-center gap-2.5">
            <span className="text-[15px]">🧠</span>
            <SectionLabel accent>What was learned</SectionLabel>
          </div>
          <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--color-paper)" }}>
            {learning.lesson ?? `Ended ${learning.outcome ?? "without resolution"}.`}
          </p>
          <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            {record.suitable_for_hindsight ? "Retained in organizational memory · Powered by Hindsight" : "Not retained"}
          </p>
        </Card>
      )}

      <div className="flex flex-wrap gap-2.5">
        <BackButton onBack={onBack} />
        <button
          type="button"
          onClick={onSimulate}
          className="rounded-lg px-5 py-2.5 text-[13px] font-medium transition-transform hover:scale-[1.02]"
          style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
        >
          ⚡ Inject Fault
        </button>
      </div>

      <p className="font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
        {investigation.length} investigation steps · {record.recalled_memory_count} memories recalled
        {record.injected_fault_type ? ` · injected fault: ${record.injected_fault_type}` : ""}
      </p>
    </div>
  )
}

function LoopCell({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>{k}</div>
      <div className="tnum mt-1 text-[14px]" style={{ color: "var(--color-paper-dim)" }}>{v}</div>
    </div>
  )
}

function BackButton({ onBack }: { onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="rounded-lg border px-5 py-2.5 text-[13px] font-medium transition-colors"
      style={{ borderColor: "var(--color-line-strong)", color: "var(--color-paper-dim)" }}
    >
      ← All incidents
    </button>
  )
}

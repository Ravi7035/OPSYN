import { useEffect, useState } from "react"
import { listIncidents, type IncidentRecord } from "../lib/api"
import LoopCycle, { LoopStrip } from "./LoopCycle"
import { Card, Dot, SectionLabel, SignalPill } from "./ui"

/* ---------------------------------- Overview ---------------------------------- */

const ACTION_LABELS_OVERVIEW: Record<string, string> = {
  rollback_deployment: "Rolled back to the previous release.",
  restart_service: "Restarted the payment service.",
  clear_db_connections: "Cleared stale DB connections.",
  restart_redis: "Restarted the Redis cache.",
  restore_dependency: "Restored the downstream dependency.",
  scale_service: "Scaled service capacity.",
  clear_queue: "Drained the request queue.",
  free_disk: "Reclaimed disk space.",
}

type RecentExperience = {
  id: string
  title: string
  when: string
  discovered: string
  action: string
  outcome: string
  resolved: boolean
  lesson: string
}

function recentFromRecords(records: IncidentRecord[]): RecentExperience[] {
  return [...records]
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .slice(0, 4)
    .map((r) => {
      const before = r.verification_result?.metrics_before?.http_5xx_rate
      const after = r.verification_result?.metrics_after?.http_5xx_rate
      const outcome =
        r.status === "RESOLVED" && before !== undefined && after !== undefined
          ? `5xx ${before}% → ${after}% — recovery verified.`
          : r.status === "RESOLVED"
            ? "Recovery verified."
            : `Ended ${r.status.toLowerCase()} without verified recovery.`
      return {
        id: r.incident_id,
        title: r.title,
        when: timeAgo(r.created_at),
        discovered:
          r.detected_symptoms.slice(0, 2).join("; ") || "Under investigation.",
        action: r.selected_action
          ? (ACTION_LABELS_OVERVIEW[r.selected_action] ?? r.selected_action)
          : "No remediation verified yet.",
        outcome,
        resolved: r.status === "RESOLVED",
        lesson: r.learning_lesson ?? "Experience retained for future investigations.",
      }
    })
}

function statsFromRecords(records: IncidentRecord[]): { value: string; label: string }[] {
  const resolved = records.filter((r) => r.status === "RESOLVED")
  const failed = records.filter((r) => r.status === "FAILED" || r.status === "UNRESOLVED")
  const diagnoses = new Set(
    records.map((r) => r.diagnosis).filter((d): d is string => !!d),
  )
  return [
    { value: `${records.length}`, label: "incidents remembered" },
    { value: `${resolved.length}`, label: "successful remediations" },
    { value: `${failed.length}`, label: "failed approaches remembered" },
    { value: `${diagnoses.size}`, label: "recurring patterns" },
  ]
}

export function Overview({
  onSimulate,
}: {
  onSimulate: () => void
}) {
  const [records, setRecords] = useState<IncidentRecord[] | null>(null)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    let live = true
    listIncidents()
      .then((body) => live && setRecords(body.incidents))
      .catch(() => {
        if (!live) return
        setLoadError(true)
        setRecords([])
      })
    return () => {
      live = false
    }
  }, [])

  const stats = records === null ? null : statsFromRecords(records)
  const recent = records === null ? null : recentFromRecords(records)
  return (
    <div className="flex flex-col gap-14">
      {/* hero */}
      <div className="grid items-center gap-10 pt-8 lg:grid-cols-[1fr_360px] lg:pt-14">
        <div className="max-w-2xl">
          <SectionLabel accent>AI Incident Response Engineer</SectionLabel>
          <h1 className="mt-5 font-display text-5xl font-semibold leading-[0.98] tracking-tight sm:text-6xl" style={{ color: "var(--color-paper)" }}>
            OPSYN
          </h1>
          <p className="mt-5 max-w-xl text-xl leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
            Resolve incidents with the experience of every incident that came before.
          </p>
          <p className="mt-4 max-w-xl text-[15px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
            OPSYN remembers how your systems behaved before, learns how incidents were resolved, and carries that organizational experience into every new investigation.
          </p>
          <div className="mt-7">
            <LoopStrip />
          </div>
        </div>
        <div className="hidden lg:block">
          <LoopCycle />
        </div>
      </div>

      {/* active incident */}
      <div>
        <SectionLabel>Active incident</SectionLabel>
        <div
          className="mt-4 rounded-xl border border-dashed p-6 sm:p-8"
          style={{
            borderColor: "var(--color-line-strong)",
            background: "var(--color-ink-850)",
          }}
        >
          <div className="flex items-center gap-2.5">
            <Dot tone="neutral" />
            <span
              className="text-[15px] font-medium"
              style={{ color: "var(--color-paper)" }}
            >
              No active incident
            </span>
          </div>
          <p
            className="mt-2 max-w-xl text-[13px] leading-relaxed"
            style={{ color: "var(--color-paper-faint)" }}
          >
            Inject a controlled fault into the payment environment
            to observe how OPSYN investigates and responds.
          </p>
          <button
            type="button"
            onClick={onSimulate}
            className="mt-5 rounded-lg px-5 py-2.5 text-[13px] font-medium transition-transform hover:scale-[1.02]"
            style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
          >
            ⚡ Inject Fault
          </button>
        </div>
      </div>

      {/* organizational experience */}
      <div>
        <SectionLabel>Organizational experience</SectionLabel>
        <div className="mt-4 grid gap-px overflow-hidden rounded-xl border sm:grid-cols-2 lg:grid-cols-4" style={{ borderColor: "var(--color-line)", background: "var(--color-line)" }}>
          {(stats ?? []).map((s) => (
            <div key={s.label} className="flex flex-col gap-1 p-6" style={{ background: "var(--color-ink-850)" }}>
              <span className="tnum font-display text-4xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>{s.value}</span>
              <span className="text-[13px]" style={{ color: "var(--color-paper-faint)" }}>{s.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* recent experience */}
      <div>
        <SectionLabel>Recent experience</SectionLabel>
        {recent === null && (
          <p className="mt-4 text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
            Loading organizational experience…
          </p>
        )}
        {recent !== null && recent.length === 0 && (
          <p className="mt-4 max-w-xl text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
            {loadError
              ? "Organizational experience is unreachable right now — start the backend to load it."
              : "Nothing retained yet. Resolve an incident and its experience will appear here."}
          </p>
        )}
        {recent !== null && recent.length > 0 && (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {recent.map((r) => (
              <Card key={r.id} className="p-5 hover-lift">
                <div className="flex items-center gap-3">
                  <Dot tone={r.resolved ? "good" : "neutral"} />
                  <span className="text-[15px] font-medium" style={{ color: "var(--color-paper)" }}>{r.title}</span>
                  <span className="ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>{r.when}</span>
                </div>
                <p className="mt-3 text-[13px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>{r.discovered}</p>
                <div className="mt-4 flex flex-col gap-2 border-t pt-3" style={{ borderColor: "var(--color-line)" }}>
                  <MiniRow k="Action" v={r.action} />
                  <MiniRow k="Outcome" v={r.outcome} tone={r.resolved ? "good" : undefined} />
                  <MiniRow k="Lesson" v={r.lesson} tone="accent" />
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function MiniRow({ k, v, tone }: { k: string; v: string; tone?: "good" | "accent" }) {
  return (
    <div className="flex gap-3 text-[13px]">
      <span className="w-16 shrink-0 font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>{k}</span>
      <span style={{ color: tone === "good" ? "var(--color-good)" : tone === "accent" ? "var(--color-accent)" : "var(--color-paper-dim)" }}>{v}</span>
    </div>
  )
}

/* --------------------------------- Incidents --------------------------------- */

export function Incidents({
  onOpenIncident,
  onSimulate,
}: {
  onOpenIncident: (incidentId: string) => void
  onSimulate: () => void
}) {
  const [records, setRecords] = useState<IncidentRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    listIncidents()
      .then((body) => live && setRecords(body.incidents))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [])

  return (
    <div className="flex flex-col gap-8 pt-4">
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>Incidents</h1>
        <p className="mt-2 text-[15px]" style={{ color: "var(--color-paper-dim)" }}>Every incident OPSYN has investigated — recorded by the backend, never invented.</p>
      </div>

      {records === null && error === null && (
        <Card className="p-6">
          <p className="text-[14px]" style={{ color: "var(--color-paper-faint)" }}>
            Loading incident history…
          </p>
        </Card>
      )}

      {error !== null && (
        <Card className="p-6">
          <SectionLabel>History unavailable</SectionLabel>
          <p className="mt-2 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
            {error}
          </p>
        </Card>
      )}

      {records !== null && records.length === 0 && error === null && (
        <div
          className="rounded-xl border border-dashed p-6 sm:p-8"
          style={{
            borderColor: "var(--color-line-strong)",
            background: "var(--color-ink-850)",
          }}
        >
          <div className="font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            No incidents yet
          </div>
          <p className="mt-2 max-w-xl text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
            No production incidents have been recorded. Inject a controlled
            fault to create the first real incident record.
          </p>
          <button
            type="button"
            onClick={onSimulate}
            className="mt-5 rounded-lg px-5 py-2.5 text-[13px] font-medium transition-transform hover:scale-[1.02]"
            style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
          >
            ⚡ Inject Fault
          </button>
        </div>
      )}

      {records !== null && records.length > 0 && (
        <div className="relative flex flex-col gap-3 pl-6">
          <span className="absolute bottom-2 left-[7px] top-2 w-px" style={{ background: "var(--color-line)" }} />
          {records.map((r) => (
            <div key={r.incident_id} className="relative">
              <span className="absolute -left-[22px] top-6 flex h-3.5 w-3.5 items-center justify-center rounded-full" style={{ background: "var(--color-ink-950)" }}>
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: statusColor(r.status) }}
                />
              </span>
              <button type="button" onClick={() => onOpenIncident(r.incident_id)} className="group block w-full text-left">
                <Card className="p-5 hover-lift">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>{r.incident_id}</span>
                    <span className="text-[16px] font-medium" style={{ color: "var(--color-paper)" }}>{r.title}</span>
                    <StatusBadge status={r.status} />
                    <span className="ml-auto font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>
                      {formatWhen(r.created_at)}
                    </span>
                  </div>
                  <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <TLField k="Service" v={r.service} />
                    <TLField k="Duration" v={formatDuration(r.created_at, r.resolved_at)} />
                    <TLField k="Action" v={r.selected_action ? humanAction(r.selected_action) : "—"} />
                    <TLField
                      k="Outcome"
                      v={r.status === "RESOLVED" ? "Recovery verified" : statusLabel(r.status)}
                      tone={r.status === "RESOLVED" ? "good" : undefined}
                    />
                  </div>
                  <div className="mt-3 font-mono text-[11px] uppercase tracking-wider transition-transform group-hover:translate-x-1" style={{ color: "var(--color-accent)" }}>
                    Open investigation →
                  </div>
                </Card>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const ACTIVE_STATUSES = new Set([
  "INJECTED",
  "INVESTIGATING",
  "REMEDIATING",
  "VERIFYING",
])

function statusColor(status: string): string {
  if (status === "RESOLVED") return "var(--color-good)"
  if (status === "FAILED") return "var(--color-fail)"
  if (ACTIVE_STATUSES.has(status)) return "var(--color-critical)"
  return "var(--color-paper-ghost)"
}

function statusLabel(status: string): string {
  if (status === "RESOLVED") return "Resolved"
  if (status === "FAILED") return "Failed"
  if (status === "UNRESOLVED") return "Unresolved"
  if (ACTIVE_STATUSES.has(status)) return "Investigating"
  return status
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "RESOLVED"
      ? "rgba(99,201,154,0.25)"
      : status === "FAILED"
        ? "rgba(224,132,151,0.3)"
        : "rgba(240,163,94,0.3)"
  const text =
    status === "RESOLVED"
      ? "var(--color-good)"
      : status === "FAILED"
        ? "var(--color-fail)"
        : status === "UNRESOLVED"
          ? "var(--color-paper-dim)"
          : "var(--color-critical)"
  return (
    <span
      className="rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
      style={{ borderColor: color, color: text }}
    >
      {status}
    </span>
  )
}

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function formatDuration(createdAt: string, resolvedAt: string | null): string {
  const start = new Date(createdAt).getTime()
  const end = resolvedAt ? new Date(resolvedAt).getTime() : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—"
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s${resolvedAt ? "" : " so far"}`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}m ${rest}s`
}

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

function humanAction(action: string): string {
  return ACTION_LABELS[action] ?? action
}

function TLField({ k, v, tone }: { k: string; v: string; tone?: "good" | "accent" }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>{k}</div>
      <div className="mt-1.5 text-[13px] leading-relaxed" style={{ color: tone === "good" ? "var(--color-good)" : tone === "accent" ? "var(--color-accent)" : "var(--color-paper-dim)" }}>{v}</div>
    </div>
  )
}

/* ---------------------------------- Memory ---------------------------------- */

type MemoryStoryView = {
  category: string
  title: string
  seen: string
  signals: string[]
  worked?: string
  failed?: string
  lesson: string
}

function timeAgo(iso: string): string {
  const at = new Date(iso).getTime()
  if (!Number.isFinite(at)) return "unknown time"
  const seconds = Math.max(0, Math.round((Date.now() - at) / 1000))
  if (seconds < 60) return "just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? "" : "s"} ago`
}

function shortSignal(text: string): string {
  const cleaned = text.replace(/^\d{4}-\d{2}-\d{2}T\S+\s*/, "").trim()
  return cleaned.length > 64 ? `${cleaned.slice(0, 64)}…` : cleaned || text
}

/** Derive the Memory template's stories purely from persisted records. */
function storiesFromRecords(records: IncidentRecord[]): MemoryStoryView[] {
  const stories: MemoryStoryView[] = []
  for (const r of records) {
    const seen = timeAgo(r.created_at)
    const signals = r.detected_symptoms.slice(0, 3).map(shortSignal)
    if (r.diagnosis) signals.unshift(r.diagnosis)
    const lesson =
      r.learning_lesson ?? `Investigation ended ${r.status.toLowerCase()}.`
    stories.push({
      category: "incidents",
      title: r.title,
      seen: `${r.incident_id} · ${seen}`,
      signals: signals.slice(0, 4),
      worked: r.selected_action ?? undefined,
      lesson,
    })
    if (r.status === "RESOLVED" && r.selected_action) {
      stories.push({
        category: "successful",
        title: r.selected_action,
        seen: `${r.incident_id} · ${seen}`,
        signals: signals.slice(0, 3),
        worked: `Recovered ${r.verification_result?.improved ? "with verified improvement" : ""}`.trim(),
        lesson: r.learning_lesson ?? "Remediation verified by re-observation.",
      })
    }
    if (r.status === "FAILED" || r.status === "UNRESOLVED") {
      stories.push({
        category: "failed",
        title: r.selected_action ?? r.title,
        seen: `${r.incident_id} · ${seen}`,
        signals: signals.slice(0, 3),
        failed: r.action_result ?? `Ended ${r.status.toLowerCase()} without verified recovery`,
        lesson: r.learning_lesson ?? "Recorded so future runs avoid this path.",
      })
    }
    if (r.learning_lesson) {
      stories.push({
        category: "lessons",
        title: r.diagnosis ?? r.title,
        seen: `${r.incident_id} · ${seen}`,
        signals: signals.slice(0, 3),
        lesson: r.learning_lesson,
      })
    }
  }
  // Recurring patterns: group resolved records by diagnosis.
  const byDiagnosis = new Map<string, IncidentRecord[]>()
  for (const r of records) {
    if (r.status !== "RESOLVED" || !r.diagnosis) continue
    const group = byDiagnosis.get(r.diagnosis) ?? []
    group.push(r)
    byDiagnosis.set(r.diagnosis, group)
  }
  for (const [diagnosis, group] of byDiagnosis) {
    const actionCounts = new Map<string, number>()
    for (const r of group) {
      if (r.selected_action) actionCounts.set(r.selected_action, (actionCounts.get(r.selected_action) ?? 0) + 1)
    }
    const topAction = [...actionCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    const latestLesson = group
      .map((r) => r.learning_lesson)
      .find((lesson): lesson is string => !!lesson)
    stories.push({
      category: "patterns",
      title: diagnosis,
      seen: `Seen ${group.length} time${group.length === 1 ? "" : "s"}`,
      signals: [diagnosis],
      worked: topAction,
      lesson: latestLesson ?? "Recurring diagnosis across retained incidents.",
    })
  }
  return stories
}

function categoriesFromStories(stories: MemoryStoryView[]): { key: string; label: string; count: number }[] {
  const count = (key: string) => stories.filter((s) => s.category === key).length
  return [
    { key: "incidents", label: "Incidents", count: count("incidents") },
    { key: "successful", label: "Successful Remediations", count: count("successful") },
    { key: "failed", label: "Failed Approaches", count: count("failed") },
    { key: "lessons", label: "Lessons", count: count("lessons") },
    { key: "patterns", label: "Recurring Patterns", count: count("patterns") },
  ]
}

export function Memory({ onSimulate }: { onSimulate: () => void }) {
  const [filter, setFilter] = useState<string>("all")
  const [stories, setStories] = useState<MemoryStoryView[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    listIncidents()
      .then((body) => live && setStories(storiesFromRecords(body.incidents)))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [])

  const categories = stories === null ? [] : categoriesFromStories(stories)
  const visible =
    stories === null
      ? []
      : filter === "all"
        ? stories
        : stories.filter((s) => s.category === filter)

  return (
    <div className="flex flex-col gap-8 pt-4">
      <div className="max-w-2xl">
        <h1 className="font-display text-3xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>Organizational Memory</h1>
        <p className="mt-2 text-[15px]" style={{ color: "var(--color-paper-dim)" }}>The experience OPSYN carries from one incident to the next.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>All</FilterChip>
        {categories.map((c) => (
          <FilterChip key={c.key} active={filter === c.key} onClick={() => setFilter(c.key)}>
            {c.label} <span className="tnum opacity-60">{c.count}</span>
          </FilterChip>
        ))}
      </div>

      {stories === null && error === null && (
        <Card className="p-6">
          <p className="text-[14px]" style={{ color: "var(--color-paper-faint)" }}>
            Loading organizational memory…
          </p>
        </Card>
      )}

      {error !== null && (
        <Card className="p-6">
          <SectionLabel>Memory unavailable</SectionLabel>
          <p className="mt-2 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
            {error}
          </p>
        </Card>
      )}

      {stories !== null && stories.length === 0 && error === null && (
        <div
          className="rounded-xl border border-dashed p-6 sm:p-8"
          style={{
            borderColor: "var(--color-line-strong)",
            background: "var(--color-ink-850)",
          }}
        >
          <div className="font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            No organizational memory yet
          </div>
          <p className="mt-2 max-w-xl text-[13px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
            No incidents have been retained yet. Inject a controlled fault
            and OPSYN&apos;s first experience will appear here.
          </p>
          <button
            type="button"
            onClick={onSimulate}
            className="mt-5 rounded-lg px-5 py-2.5 text-[13px] font-medium transition-transform hover:scale-[1.02]"
            style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
          >
            ⚡ Inject Fault
          </button>
        </div>
      )}

      {visible.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((s) => (
          <Card key={s.title} className="flex flex-col gap-3 p-5 hover-lift">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[15px] font-medium leading-snug" style={{ color: "var(--color-paper)" }}>{s.title}</span>
            </div>
            <span className="font-mono text-[11px] uppercase tracking-wider" style={{ color: "var(--color-accent)" }}>{s.seen}</span>
            <div className="flex flex-wrap gap-1.5">
              {s.signals.map((sig) => (
                <SignalPill key={sig}>{sig}</SignalPill>
              ))}
            </div>
            <div className="mt-1 flex flex-col gap-2.5 border-t pt-3" style={{ borderColor: "var(--color-line)" }}>
              {s.worked && <StoryRow k="Successful response" v={s.worked} tone="good" />}
              {s.failed && <StoryRow k="Failed response" v={s.failed} tone="fail" />}
              <StoryRow k="Lesson" v={s.lesson} tone="accent" />
            </div>
          </Card>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 text-[12px]" style={{ color: "var(--color-paper-ghost)" }}>
        <Dot tone="accent" /> Stored and recalled through Hindsight
      </div>
    </div>
  )
}

function StoryRow({ k, v, tone }: { k: string; v: string; tone?: "good" | "accent" | "fail" }) {
  const color =
    tone === "good"
      ? "var(--color-good)"
      : tone === "accent"
        ? "var(--color-accent)"
        : tone === "fail"
          ? "var(--color-fail)"
          : "var(--color-paper-dim)"
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>{k}</div>
      <div className="mt-0.5 text-[13px] leading-relaxed" style={{ color }}>{v}</div>
    </div>
  )
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="rounded-full border px-3.5 py-1.5 text-[13px] transition-colors"
      style={{
        borderColor: active ? "rgba(141,139,246,0.4)" : "var(--color-line)",
        background: active ? "rgba(141,139,246,0.1)" : "transparent",
        color: active ? "var(--color-paper)" : "var(--color-paper-faint)",
      }}
    >
      {children}
    </button>
  )
}

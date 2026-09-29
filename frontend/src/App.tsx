import { useRef, useState } from "react"
import Landing from "./components/Landing"
import LiveIncident from "./components/LiveIncident"
import IncidentDetail from "./components/IncidentDetail"
import SimulateModal from "./components/SimulateModal"
import { Incidents, Memory, Overview } from "./components/pages"
import { ThemeToggle } from "./components/ui"
import type { Scenario } from "./lib/api"

export type View = "overview" | "incidents" | "memory" | "live" | "incident-detail"
const NAV: { key: View; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "incidents", label: "Incidents" },
  { key: "memory", label: "Memory" },
]

export default function App() {
  const [entered, setEntered] = useState(false)
  const [view, setView] = useState<View>("overview")
  const [simulateOpen, setSimulateOpen] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [liveScenario, setLiveScenario] = useState<Scenario | null>(null)
  const [liveKey, setLiveKey] = useState(0)
  const [detailRecordId, setDetailRecordId] = useState<string | null>(null)
  // Session-scoped learning counters. Every increment comes from a real
  // completed agent run (see LiveIncident's onRunComplete): incidents
  // handled, agent-side Hindsight recalls, and experiences stored.
  const [sessionStats, setSessionStats] = useState({ incidents: 0, recalled: 0, stored: 0 })
  const countedRunRef = useRef<string | null>(null)
  const recordRunComplete = (incidentId: string, delta: { recalled: number; stored: number }) => {
    if (countedRunRef.current === incidentId) return
    countedRunRef.current = incidentId
    setSessionStats((s) => ({
      incidents: s.incidents + 1,
      recalled: s.recalled + delta.recalled,
      stored: s.stored + delta.stored,
    }))
  }

  const enter = (target: View = "overview") => {
    setView(target)
    setEntered(true)
    window.scrollTo({ top: 0 })
  }

  if (!entered) return <Landing onEnter={enter} />

  const navTo = (v: View) => {
    setView(v)
    window.scrollTo({ top: 0 })
  }

  const openIncidentDetail = (recordId: string) => {
    setDetailRecordId(recordId)
    setView("incident-detail")
    window.scrollTo({ top: 0 })
  }

  const startLiveRun = (scenario: Scenario) => {
    setTriggering(true)
    // The modal closes immediately; the workspace injects the fault and
    // investigates. A fresh key restarts the run for repeat simulations.
    setLiveScenario(scenario)
    setLiveKey((k) => k + 1)
    setSimulateOpen(false)
    setTriggering(false)
    setView("live")
    window.scrollTo({ top: 0 })
  }

  return (
    <div className="relative min-h-screen">
      <div className="aurora" />
      <div className="relative z-10">
      {/* top navigation */}
      <header
        className="sticky top-0 z-30 border-b backdrop-blur-xl"
        style={{ borderColor: "var(--color-line)", background: "var(--color-header-bg)" }}
      >
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
          <button
            type="button"
            onClick={() => setEntered(false)}
            aria-label="Back to the OPSYN story"
            className="flex items-center gap-2.5"
          >
            <span
              className="flex h-6 w-6 items-center justify-center rounded-md"
              style={{ background: "linear-gradient(135deg, var(--color-accent), var(--color-accent-dim))" }}
            >
              <span className="h-2 w-2 rounded-[2px] bg-white/90" />
            </span>
            <span className="font-display text-[15px] font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>
              OPSYN
            </span>
          </button>

          <nav className="flex items-center gap-1">
            {NAV.map((n) => {
              const active = view === n.key
              return (
                <button
                  key={n.key}
                  type="button"
                  onClick={() => navTo(n.key)}
                  className="rounded-md px-3 py-1.5 text-[13px] transition-colors"
                  style={{
                    color: active ? "var(--color-paper)" : "var(--color-paper-faint)",
                    background: active ? "var(--color-hover-wash)" : "transparent",
                  }}
                >
                  {n.label}
                </button>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-28">
        {view === "overview" && (
          <Overview
            onSimulate={() => setSimulateOpen(true)}
          />
        )}
        {view === "incidents" && (
          <Incidents
            onOpenIncident={openIncidentDetail}
            onSimulate={() => setSimulateOpen(true)}
          />
        )}
        {view === "incident-detail" && detailRecordId && (
          <IncidentDetail
            key={detailRecordId}
            recordId={detailRecordId}
            onBack={() => navTo("incidents")}
            onSimulate={() => setSimulateOpen(true)}
          />
        )}
        {view === "memory" && <Memory onSimulate={() => setSimulateOpen(true)} />}
        {view === "live" && liveScenario && (
          <LiveIncident
            key={liveKey}
            scenario={liveScenario}
            sessionKey={liveKey}
            sessionStats={sessionStats}
            onRunComplete={recordRunComplete}
            onSimulateAnother={() => setSimulateOpen(true)}
            onExit={() => navTo("overview")}
          />
        )}
      </main>

      <footer className="border-t" style={{ borderColor: "var(--color-line)" }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
          <button
            type="button"
            onClick={() => setEntered(false)}
            className="font-display text-[13px] font-medium transition-colors"
            style={{ color: "var(--color-paper-faint)" }}
          >
            ← Back to story
          </button>
          <span className="font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
            Powered by Hindsight
          </span>
        </div>
      </footer>
      </div>
      {simulateOpen && (
        <SimulateModal
          onClose={() => setSimulateOpen(false)}
          onTrigger={startLiveRun}
          triggering={triggering}
        />
      )}
    </div>
  )
}

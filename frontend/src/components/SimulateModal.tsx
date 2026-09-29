import { useEffect, useState } from "react"
import { checkBackend, SCENARIOS, type Scenario } from "../lib/api"
import { Card, Dot, SectionLabel } from "./ui"

/**
 * Fault-injection panel for the simulation operator. The operator picks a
 * failure mode to inject; the diagnosis is never entered here and never
 * reaches the agent — only the fault id goes to the simulator's
 * injection endpoint.
 */
export default function SimulateModal({
  onClose,
  onTrigger,
  triggering,
}: {
  onClose: () => void
  onTrigger: (scenario: Scenario) => void
  triggering: boolean
}) {
  const [selected, setSelected] = useState<Scenario>(SCENARIOS[0])
  const [backendOk, setBackendOk] = useState<boolean | null>(null)

  useEffect(() => {
    let live = true
    checkBackend()
      .then(() => live && setBackendOk(true))
      .catch(() => live && setBackendOk(false))
    return () => {
      live = false
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(4,5,7,0.72)", backdropFilter: "blur(6px)" }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="simulate-title"
    >
      <Card
        glow
        className="max-h-[88vh] w-full max-w-2xl overflow-y-auto p-6 sm:p-8"
      >
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <SectionLabel accent>Fault injection</SectionLabel>
              <h2
                id="simulate-title"
                className="mt-3 font-display text-2xl font-semibold tracking-tight"
                style={{ color: "var(--color-paper)" }}
              >
                Inject a Fault
              </h2>
              <p
                className="mt-2 max-w-lg text-[14px] leading-relaxed"
                style={{ color: "var(--color-paper-dim)" }}
              >
                Introduce a controlled fault into the payment environment
                and watch OPSYN investigate it. You choose the fault —
                OPSYN discovers the cause from observable signals alone.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md border px-2.5 py-1 font-mono text-[12px] transition-colors"
              style={{
                borderColor: "var(--color-line)",
                color: "var(--color-paper-faint)",
              }}
            >
              ✕
            </button>
          </div>

          {backendOk === false && (
            <div
              className="mt-5 rounded-lg border p-4 text-[13px] leading-relaxed"
              style={{
                borderColor: "rgba(240,163,94,0.35)",
                background: "rgba(240,163,94,0.06)",
                color: "var(--color-paper-dim)",
              }}
              role="alert"
            >
              The OPSYN backend is unreachable. Start it with
              <span
                className="tnum ml-1 font-mono"
                style={{ color: "var(--color-paper)" }}
              >
                uvicorn app.main:app
              </span>{" "}
              from <span className="tnum font-mono">backend/</span>, then
              reopen this panel.
            </div>
          )}

          <div
            className="mt-6 grid gap-2.5 sm:grid-cols-2"
            role="radiogroup"
            aria-label="Fault scenario"
          >
            {SCENARIOS.map((s) => {
              const active = s.fault === selected.fault
              return (
                <button
                  key={s.fault}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setSelected(s)}
                  className="rounded-lg border p-4 text-left transition-all hover:scale-[1.01]"
                  style={{
                    borderColor: active
                      ? "rgba(141,139,246,0.45)"
                      : "var(--color-line)",
                    background: active
                      ? "rgba(141,139,246,0.07)"
                      : "var(--color-ink-800)",
                  }}
                >
                  <div className="flex items-center gap-2">
                    <Dot tone={active ? "accent" : "critical"} live={active} />
                    <span
                      className="text-[14px] font-medium"
                      style={{ color: "var(--color-paper)" }}
                    >
                      {s.label}
                    </span>
                  </div>
                  <p
                    className="mt-1.5 text-[12.5px] leading-relaxed"
                    style={{ color: "var(--color-paper-faint)" }}
                  >
                    {s.blurb}
                  </p>
                </button>
              )
            })}
          </div>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              type="button"
              disabled={triggering || backendOk === false}
              onClick={() => onTrigger(selected)}
              className="rounded-lg px-6 py-3 text-[14px] font-medium transition-transform hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100"
              style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
            >
              {triggering ? "Injecting fault…" : "Inject Fault →"}
            </button>
            <p
              className="text-[12px] leading-relaxed"
              style={{ color: "var(--color-paper-ghost)" }}
            >
              The simulator changes — OPSYN only sees the resulting metrics,
              logs, and health. The diagnosis is never sent.
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}

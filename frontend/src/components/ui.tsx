import type { ReactNode } from "react"
import type { Signal } from "../lib/data"
import { useTheme } from "../lib/theme"

export function SectionLabel({
  children,
  accent,
}: {
  children: ReactNode
  accent?: boolean
}) {
  return (
    <div
      className="font-mono text-[11px] uppercase tracking-[0.2em]"
      style={{ color: accent ? "var(--color-accent)" : "var(--color-paper-faint)" }}
    >
      {children}
    </div>
  )
}

export function Dot({
  tone = "neutral",
  live,
}: {
  tone?: "critical" | "good" | "neutral" | "accent"
  live?: boolean
}) {
  const color =
    tone === "critical"
      ? "var(--color-critical)"
      : tone === "good"
        ? "var(--color-good)"
        : tone === "accent"
          ? "var(--color-accent)"
          : "var(--color-paper-ghost)"
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0" style={{ color }}>
      {live && <span className="ping absolute inset-0" />}
      <span
        className={`inline-flex h-2 w-2 rounded-full ${live ? "live-dot" : ""}`}
        style={{ backgroundColor: color }}
      />
    </span>
  )
}

export function Card({
  children,
  className = "",
  glow,
}: {
  children: ReactNode
  className?: string
  glow?: boolean
}) {
  return (
    <div
      className={`relative rounded-xl border ${className}`}
      style={{
        borderColor: glow ? "rgba(141,139,246,0.25)" : "var(--color-line)",
        background: glow
          ? "linear-gradient(180deg, rgba(141,139,246,0.06), rgba(255,255,255,0.008))"
          : "var(--color-ink-850)",
      }}
    >
      {children}
    </div>
  )
}

const toneColor = (tone?: Signal["tone"]) =>
  tone === "critical"
    ? "var(--color-critical)"
    : tone === "good"
      ? "var(--color-good)"
      : "var(--color-paper-dim)"

export function SignalMeter({ signal }: { signal: Signal }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
          {signal.label}
        </span>
        <span
          className="tnum font-mono text-sm font-medium"
          style={{ color: toneColor(signal.tone) }}
        >
          {signal.value}
        </span>
      </div>
      {signal.fill !== undefined && (
        <div
          className="h-[3px] w-full overflow-hidden rounded-full"
          style={{ background: "var(--color-track)" }}
        >
          <div
            className="bar-fill h-full rounded-full"
            style={{
              width: `${Math.max(signal.fill * 100, 3)}%`,
              background: toneColor(signal.tone),
              opacity: 0.85,
            }}
          />
        </div>
      )}
    </div>
  )
}

export function Fact({ signal }: { signal: Signal }) {
  return (
    <div className="flex items-center gap-2.5">
      <Dot tone={signal.tone === "neutral" ? "neutral" : signal.tone} />
      <span className="text-[13px]" style={{ color: "var(--color-paper-faint)" }}>
        {signal.label}
      </span>
      <span
        className="tnum ml-auto font-mono text-[13px]"
        style={{ color: toneColor(signal.tone) }}
      >
        {signal.value}
      </span>
    </div>
  )
}

export function RiskTag({ risk }: { risk: "Low" | "Medium" | "High" }) {
  const tone =
    risk === "Low"
      ? "var(--color-good)"
      : risk === "High"
        ? "var(--color-critical)"
        : "var(--color-paper-dim)"
  return (
    <span
      className="font-mono text-[11px] uppercase tracking-wider"
      style={{ color: tone }}
    >
      {risk} risk
    </span>
  )
}

export function SignalPill({ children }: { children: ReactNode }) {
  return (
    <span
      className="rounded-md border px-2 py-0.5 text-[12px]"
      style={{
        borderColor: "var(--color-line)",
        color: "var(--color-paper-dim)",
        background: "rgba(255,255,255,0.02)",
      }}
    >
      {children}
    </span>
  )
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const light = theme === "light"
  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={light}
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
      title={light ? "Switch to dark theme" : "Switch to light theme"}
      className="flex h-8 w-8 items-center justify-center rounded-lg border transition-colors"
      style={{
        borderColor: "var(--color-line)",
        color: "var(--color-paper-faint)",
        background: "transparent",
      }}
    >
      {light ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      )}
    </button>
  )
}

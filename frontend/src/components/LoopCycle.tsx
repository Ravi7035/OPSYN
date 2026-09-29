import { useEffect, useState } from "react"

const PHASES = [
  { key: "observe", label: "Observe", note: "Read current signals" },
  { key: "remember", label: "Remember", note: "Recall past incidents" },
  { key: "reason", label: "Reason", note: "Compare & weigh evidence" },
  { key: "act", label: "Act", note: "Apply safest remedy" },
  { key: "verify", label: "Verify", note: "Confirm recovery" },
  { key: "learn", label: "Learn", note: "Retain the experience" },
] as const

/**
 * The product's core loop, rendered as a calm ring with a single
 * highlight travelling through each phase.
 */
export default function LoopCycle() {
  const [active, setActive] = useState(0)

  useEffect(() => {
    const t = window.setInterval(() => {
      setActive((a) => (a + 1) % PHASES.length)
    }, 1400)
    return () => window.clearInterval(t)
  }, [])

  const R = 118
  const cx = 150
  const cy = 150

  return (
    <div className="relative mx-auto aspect-square w-full max-w-[340px]">
      <svg viewBox="0 0 300 300" className="h-full w-full">
        {/* base ring */}
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
        {/* progress arc following the active node */}
        <circle
          cx={cx}
          cy={cy}
          r={R}
          fill="none"
          stroke="var(--color-accent)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray={`${(2 * Math.PI * R) / PHASES.length - 14} ${2 * Math.PI * R}`}
          strokeDashoffset={`${-((2 * Math.PI * R) / PHASES.length) * active + 7}`}
          style={{ transition: "stroke-dashoffset 0.9s cubic-bezier(0.16,1,0.3,1)", opacity: 0.7 }}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        {/* nodes */}
        {PHASES.map((_, i) => {
          const ang = (i / PHASES.length) * 2 * Math.PI - Math.PI / 2
          const x = cx + R * Math.cos(ang)
          const y = cy + R * Math.sin(ang)
          const on = i === active
          return (
            <g key={i}>
              {on && <circle cx={x} cy={y} r="9" fill="var(--color-accent)" opacity="0.16" />}
              <circle
                cx={x}
                cy={y}
                r={on ? 4 : 2.5}
                fill={on ? "var(--color-accent)" : "rgba(255,255,255,0.28)"}
                style={{ transition: "all 0.6s ease" }}
              />
            </g>
          )
        })}
      </svg>

      {/* center label */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="font-mono text-[10px] uppercase tracking-[0.24em]" style={{ color: "var(--color-paper-ghost)" }}>
          The loop
        </span>
        <span key={active} className="rise mt-2 font-display text-2xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>
          {PHASES[active].label}
        </span>
        <span key={`n${active}`} className="rise mt-1 max-w-[9rem] text-[12px] leading-snug" style={{ color: "var(--color-paper-faint)" }}>
          {PHASES[active].note}
        </span>
      </div>
    </div>
  )
}

export function LoopStrip() {
  const [active, setActive] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setActive((a) => (a + 1) % PHASES.length), 1400)
    return () => window.clearInterval(t)
  }, [])
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
      {PHASES.map((p, i) => (
        <div key={p.key} className="flex items-center gap-2">
          <span
            className="loop-node rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em]"
            style={{
              borderColor: i === active ? "rgba(141,139,246,0.5)" : "var(--color-line)",
              background: i === active ? "rgba(141,139,246,0.12)" : "transparent",
              color: i === active ? "var(--color-paper)" : "var(--color-paper-ghost)",
              transform: i === active ? "translateY(-1px)" : "none",
            }}
          >
            {p.label}
          </span>
          {i < PHASES.length - 1 && (
            <span className="h-px w-3" style={{ background: "var(--color-line)" }} />
          )}
        </div>
      ))}
    </div>
  )
}

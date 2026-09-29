import type { View } from "../App"
import { Card, Dot, SectionLabel, SignalPill, ThemeToggle } from "./ui"
import Reveal from "./Reveal"

export default function Landing({ onEnter }: { onEnter: (v?: View) => void }) {
  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })

  return (
    <div className="relative">
      {/* ---- top bar ---- */}
      <header className="sticky top-0 z-30 border-b backdrop-blur-xl" style={{ borderColor: "var(--color-line)", background: "var(--color-header-bg)" }}>
        <div className="mx-auto flex max-w-6xl items-center px-6 py-4">
          <div className="flex items-center gap-2.5">
            <Logo />
            <span className="font-display text-[15px] font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>OPSYN</span>
          </div>
          <div className="ml-auto flex items-center gap-2.5">
            <ThemeToggle />
            <button
              type="button"
              onClick={() => onEnter("overview")}
              className="rounded-lg px-4 py-2 text-[13px] font-medium transition-transform hover:scale-[1.03]"
              style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
            >
              Enter OPSYN →
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6">
        {/* ============================ HERO / PAIN ============================ */}
        <section className="grid items-center gap-12 pb-24 pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:pt-24">
          <Reveal>
            <SectionLabel accent>AI Incident Response Engineer</SectionLabel>
            <h1 className="mt-6 font-display text-[2.75rem] font-semibold leading-[1.04] tracking-tight sm:text-[3.4rem]" style={{ color: "var(--color-paper)" }}>
              Your production incidents keep repeating.
              <span className="block" style={{ color: "var(--color-paper-faint)" }}>
                Your organization shouldn&apos;t keep relearning them.
              </span>
            </h1>
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
              Every incident leaves behind valuable engineering experience — what happened, what was tried, what worked, and what to avoid next time. OPSYN turns that experience into organizational memory and uses it during the next incident.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => onEnter("overview")}
                className="rounded-lg px-5 py-3 text-[14px] font-medium transition-transform hover:scale-[1.03]"
                style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
              >
                Get Started →
              </button>
              <button
                type="button"
                onClick={() => scrollTo("how")}
                className="rounded-lg border px-5 py-3 text-[14px] font-medium transition-colors"
                style={{ borderColor: "var(--color-line-strong)", color: "var(--color-paper-dim)" }}
              >
                See How OPSYN Works
              </button>
            </div>
          </Reveal>

          <Reveal delay={120}>
            <HeroVisual />
          </Reveal>
        </section>

        {/* ============================ THE PROBLEM ============================ */}
        <section className="border-t py-24" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <SectionLabel>The problem</SectionLabel>
            <h2 className="mt-5 max-w-3xl font-display text-4xl font-semibold leading-[1.08] tracking-tight" style={{ color: "var(--color-paper)" }}>
              Incident response is experienced. But most systems don&apos;t remember the experience.
            </h2>
          </Reveal>

          <div className="mt-14 grid gap-4 lg:grid-cols-3">
            {PROBLEMS.map((p, i) => (
              <Reveal key={p.no} delay={i * 90}>
                <Card className="hover-lift flex h-full flex-col gap-4 p-6">
                  <span className="font-mono text-[11px] tracking-[0.2em]" style={{ color: "var(--color-accent)" }}>{p.no}</span>
                  <h3 className="font-display text-xl font-semibold tracking-tight" style={{ color: "var(--color-paper)" }}>{p.title}</h3>
                  <p className="text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>{p.body}</p>
                  <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
                    {p.tags.map((t) => (
                      <SignalPill key={t}>{t}</SignalPill>
                    ))}
                  </div>
                </Card>
              </Reveal>
            ))}
          </div>

          <Reveal delay={120}>
            <p className="mx-auto mt-12 max-w-2xl text-center font-display text-2xl font-medium leading-snug tracking-tight" style={{ color: "var(--color-paper)" }}>
              The problem isn&apos;t only finding an answer.
              <span className="block" style={{ color: "var(--color-accent)" }}>It&apos;s knowing what worked before.</span>
            </p>
          </Reveal>
        </section>

        {/* ============================ MEET OPSYN ============================ */}
        <section id="how" className="border-t py-24" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <SectionLabel accent>Meet OPSYN</SectionLabel>
            <h2 className="mt-5 max-w-3xl font-display text-4xl font-semibold leading-[1.08] tracking-tight" style={{ color: "var(--color-paper)" }}>
              An incident-response engineer that remembers.
            </h2>
            <p className="mt-5 max-w-2xl text-[16px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
              OPSYN investigates production incidents, recalls relevant organizational experience, evaluates possible causes and actions, verifies the outcome, and retains what it learned.
            </p>
          </Reveal>

          <Reveal delay={100}>
            <div className="mt-12 flex flex-col items-stretch gap-3 md:flex-row md:flex-wrap md:items-center">
              {STORY_FLOW.map((s, i) => (
                <div key={s} className="flex items-center gap-3">
                  <div
                    className="flex-1 rounded-lg border px-4 py-3 text-center text-[13px] font-medium md:flex-none"
                    style={{
                      borderColor: s === "Hindsight" ? "rgba(141,139,246,0.4)" : "var(--color-line)",
                      background: s === "Hindsight" ? "rgba(141,139,246,0.1)" : "var(--color-ink-850)",
                      color: s === "Hindsight" ? "var(--color-accent)" : "var(--color-paper-dim)",
                    }}
                  >
                    {s}
                  </div>
                  {i < STORY_FLOW.length - 1 && (
                    <span className="hidden shrink-0 md:inline" style={{ color: "var(--color-paper-ghost)" }}>→</span>
                  )}
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        {/* ================== WITHOUT MEMORY vs WITH OPSYN ================== */}
        <section className="border-t py-24" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <SectionLabel>Organizational memory</SectionLabel>
            <h2 className="mt-5 max-w-3xl font-display text-4xl font-semibold leading-[1.08] tracking-tight" style={{ color: "var(--color-paper)" }}>
              The difference is what OPSYN remembers.
            </h2>
            <p className="mt-5 max-w-2xl text-[16px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
              Traditional incident automation reacts to the current state. OPSYN brings the organization&apos;s previous incident experience into the investigation.
            </p>
          </Reveal>

          <div className="mt-12 grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
            <Reveal>
              <Card className="h-full p-6">
                <SectionLabel>Without memory</SectionLabel>
                <FlowList items={["Incident", "Current telemetry", "Diagnosis", "Action"]} muted />
              </Card>
            </Reveal>
            <Reveal delay={100}>
              <Card glow className="h-full p-6">
                <div className="flex items-center justify-between">
                  <SectionLabel accent>With OPSYN</SectionLabel>
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>Powered by Hindsight</span>
                </div>
                <FlowList
                  items={[
                    "Incident",
                    "Current telemetry + organizational experience",
                    "Compare previous incidents",
                    "Evaluate causes",
                    "Evaluate possible actions",
                    "Choose response",
                    "Verify",
                    "Retain new experience",
                  ]}
                  highlightIndex={1}
                />
              </Card>
            </Reveal>
          </div>
        </section>

        {/* ==================== REAL INCIDENT STORY ==================== */}
        <section className="border-t py-24" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <SectionLabel accent>A live example</SectionLabel>
            <h2 className="mt-5 max-w-3xl font-display text-4xl font-semibold leading-[1.08] tracking-tight" style={{ color: "var(--color-paper)" }}>
              When the next incident arrives.
            </h2>
          </Reveal>

          <Reveal delay={100}>
            <Card className="mt-12 overflow-hidden">
              <div className="relative flex flex-col gap-8 p-6 sm:p-8">
                <span className="absolute bottom-10 left-[38px] top-24 hidden w-px sm:block" style={{ background: "var(--color-line)" }} />

                <StoryBeat n="Current incident" tone="critical">
                  <div className="text-[16px] font-semibold" style={{ color: "var(--color-paper)" }}>Payment API</div>
                  <div className="mt-3 grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-4">
                    <MiniMetric k="Error rate" v="24%" tone="critical" />
                    <MiniMetric k="P95 latency" v="2.4s" tone="critical" />
                    <MiniMetric k="DB connections" v="100 / 100" tone="critical" />
                    <MiniMetric k="Deployment" v="None" />
                  </div>
                </StoryBeat>

                <StoryBeat n="🧠 OPSYN remembers" tone="accent" label="3 similar incidents found">
                  <div className="rounded-lg border p-4" style={{ borderColor: "var(--color-line)", background: "var(--color-ink-800)" }}>
                    <div className="text-[14px] font-medium" style={{ color: "var(--color-paper)" }}>Database connection pool exhaustion</div>
                    <div className="mt-2 flex flex-wrap gap-x-8 gap-y-1 text-[13px]">
                      <span style={{ color: "var(--color-paper-faint)" }}>What worked: <span style={{ color: "var(--color-good)" }}>Clear stale connections</span></span>
                      <span style={{ color: "var(--color-paper-faint)" }}>Outcome: <span style={{ color: "var(--color-good)" }}>Recovered in 43s</span></span>
                    </div>
                  </div>
                </StoryBeat>

                <StoryBeat n="OPSYN reasons">
                  <p className="border-l-2 pl-3 text-[14px] italic leading-relaxed" style={{ borderColor: "var(--color-accent)", color: "var(--color-paper-dim)" }}>
                    “Current database saturation and latency closely match previous incidents. No recent deployment makes rollback less likely.”
                  </p>
                </StoryBeat>

                <StoryBeat n="OPSYN acts">
                  <div className="inline-flex items-center gap-2 rounded-lg border px-3 py-2" style={{ borderColor: "rgba(141,139,246,0.3)", background: "rgba(141,139,246,0.06)" }}>
                    <Dot tone="accent" /> <span className="text-[14px] font-medium" style={{ color: "var(--color-paper)" }}>Clear stale DB connections</span>
                  </div>
                </StoryBeat>

                <StoryBeat n="Verified" tone="good">
                  <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-3">
                    <MiniMetric k="Error rate" v="24% → 0.8%" tone="good" />
                    <MiniMetric k="P95 latency" v="2.4s → 310ms" tone="good" />
                    <MiniMetric k="DB connections" v="100 → 34" tone="good" />
                  </div>
                </StoryBeat>

                <StoryBeat n="🧠 Experience retained" tone="accent" last>
                  <p className="text-[14px] leading-relaxed" style={{ color: "var(--color-paper)" }}>
                    When DB saturation occurs without a recent deployment, investigate stale connections before restarting the service.
                  </p>
                </StoryBeat>
              </div>
            </Card>
          </Reveal>
        </section>

        {/* ============ FIRST → LEARNED → SECOND INCIDENT ============ */}
        <section className="border-t py-24" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <h2 className="mx-auto max-w-3xl text-center font-display text-4xl font-semibold leading-[1.1] tracking-tight" style={{ color: "var(--color-paper)" }}>
              The first incident proves OPSYN can respond.
              <span className="block" style={{ color: "var(--color-accent)" }}>The next incident proves it learned.</span>
            </h2>
          </Reveal>

          <div className="mt-14 grid items-stretch gap-4 md:grid-cols-[1fr_auto_1fr]">
            <Reveal>
              <Card className="h-full p-6">
                <SectionLabel>Incident 01</SectionLabel>
                <div className="mt-4 text-[15px] font-medium" style={{ color: "var(--color-paper)" }}>Database saturation</div>
                <FlowList items={["DB saturation", "Clear connections", "Recovery"]} highlightIndex={2} tone="good" compact />
              </Card>
            </Reveal>
            <div className="flex items-center justify-center">
              <div className="flex flex-col items-center gap-1 text-center">
                <span className="hidden text-2xl md:inline" style={{ color: "var(--color-accent)" }}>→</span>
                <span className="font-mono text-[10px] uppercase tracking-[0.16em]" style={{ color: "var(--color-paper-ghost)" }}>experience<br />retained</span>
              </div>
            </div>
            <Reveal delay={100}>
              <Card glow className="h-full p-6">
                <SectionLabel accent>Incident 02</SectionLabel>
                <div className="mt-4 text-[15px] font-medium" style={{ color: "var(--color-paper)" }}>Post-deploy error spike</div>
                <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
                  OPSYN recognizes the retained experience and applies it to the next decision — recommending a rollback because infrastructure is healthy this time.
                </p>
              </Card>
            </Reveal>
          </div>
        </section>

        {/* ============================ FINAL CTA ============================ */}
        <section className="border-t py-28 text-center" style={{ borderColor: "var(--color-line)" }}>
          <Reveal>
            <h2 className="mx-auto max-w-2xl font-display text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl" style={{ color: "var(--color-paper)" }}>
              See what OPSYN does with experience.
            </h2>
            <p className="mx-auto mt-6 max-w-xl text-[16px] leading-relaxed" style={{ color: "var(--color-paper-dim)" }}>
              Trigger an incident. Watch OPSYN investigate. See what it remembers. Follow its reasoning. Watch it recover the system — then see what it learned.
            </p>
            <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => onEnter("overview")}
                className="rounded-lg px-6 py-3 text-[15px] font-medium transition-transform hover:scale-[1.03]"
                style={{ background: "var(--color-accent)", color: "#0b0c0f" }}
              >
                Enter OPSYN →
              </button>
              <button
                type="button"
                onClick={() => onEnter("memory")}
                className="rounded-lg border px-6 py-3 text-[15px] font-medium transition-colors"
                style={{ borderColor: "var(--color-line-strong)", color: "var(--color-paper-dim)" }}
              >
                Explore Organizational Memory
              </button>
            </div>
          </Reveal>
        </section>
      </main>

      <footer className="border-t" style={{ borderColor: "var(--color-line)" }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
          <span className="font-display text-[13px] font-medium" style={{ color: "var(--color-paper-faint)" }}>OPSYN</span>
          <span className="font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>Powered by Hindsight</span>
        </div>
      </footer>
    </div>
  )
}

/* ------------------------------- pieces -------------------------------- */

function Logo() {
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ background: "linear-gradient(135deg, var(--color-accent), var(--color-accent-dim))" }}>
      <span className="h-2 w-2 rounded-[2px] bg-white/90" />
    </span>
  )
}

const PROBLEMS = [
  {
    no: "01",
    title: "Context gets lost",
    body: "When an incident hits, engineers dig through Slack, tickets, runbooks, postmortems, logs and old dashboards. The knowledge exists — it's just scattered.",
    tags: ["Slack", "Tickets", "Runbooks", "Postmortems", "Logs"],
  },
  {
    no: "02",
    title: "The same failure looks new",
    body: "A familiar incident recurs. The on-call engineer sees high latency, elevated errors and database saturation — but the organization already solved something like it before.",
    tags: ["High latency", "Elevated errors", "DB saturation"],
  },
  {
    no: "03",
    title: "Actions are not equal",
    body: "Restart the service, roll back the deploy, clear connections, scale capacity. The right action depends on context and on what actually worked last time.",
    tags: ["Restart", "Rollback", "Clear connections", "Scale"],
  },
]

const STORY_FLOW = [
  "Current incident",
  "Hindsight",
  "Past experience",
  "Reasoning",
  "Action",
  "Verified outcome",
  "New experience",
]

function FlowList({
  items,
  muted,
  highlightIndex,
  tone,
  compact,
}: {
  items: string[]
  muted?: boolean
  highlightIndex?: number
  tone?: "good"
  compact?: boolean
}) {
  return (
    <ol className={`mt-4 flex flex-col ${compact ? "gap-1.5" : "gap-2.5"}`}>
      {items.map((it, i) => {
        const hi = i === highlightIndex
        return (
          <li key={it} className="flex items-center gap-3">
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px]"
              style={{
                background: hi ? "rgba(141,139,246,0.16)" : "var(--color-hover-wash)",
                color: hi ? "var(--color-accent)" : "var(--color-paper-ghost)",
              }}
            >
              {i + 1}
            </span>
            <span
              className="text-[14px]"
              style={{
                color: hi
                  ? "var(--color-accent)"
                  : tone === "good" && i === (highlightIndex ?? -1)
                    ? "var(--color-good)"
                    : muted
                      ? "var(--color-paper-faint)"
                      : "var(--color-paper-dim)",
              }}
            >
              {it}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

/**
 * Hero visual — the product thesis in one frame:
 * scattered, slow PAST incidents flow down into OPSYN Memory,
 * which then resolves the next incident in seconds.
 * Past experience → organizational memory → a faster future.
 */
function HeroVisual() {
  const past = [
    { id: "INC-0817", t: "Database saturation", s: "Resolved manually", cost: "2h 10m" },
    { id: "INC-0834", t: "Similar symptoms", s: "Previous resolution buried in old records", cost: "55m" },
    { id: "INC-0912", t: "Same pattern again", s: "Investigated from scratch", cost: "1h 20m" },
  ]

  return (
    <div className="relative">
      {/* legend */}
      <div className="mb-4 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-paper-ghost)" }}>
          Without organizational memory
        </span>
        <span className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-accent)" }}>
          With OPSYN →
        </span>
      </div>

      <div className="relative pl-8">
        {/* spine + flowing pulse */}
        <div className="absolute bottom-3 left-[11px] top-3 w-px" style={{ background: "linear-gradient(180deg, var(--color-line), rgba(141,139,246,0.4) 55%, rgba(99,201,154,0.4))" }}>
          <span
            className="flow-dot absolute -left-[3px] h-[7px] w-[7px] rounded-full"
            style={{ background: "var(--color-accent)", boxShadow: "0 0 10px 2px rgba(141,139,246,0.5)" }}
          />
        </div>

        <div className="flex flex-col gap-3">
          {/* the fragmented past — experience that isn't reused */}
          {past.map((c) => (
            <SpineCard key={c.id} tone="past">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px]" style={{ color: "var(--color-paper-ghost)" }}>{c.id}</span>
                <span className="ml-auto font-mono text-[10px]" style={{ color: "var(--color-paper-ghost)" }}>{c.cost}</span>
              </div>
              <div className="mt-1 text-[14px] font-medium" style={{ color: "var(--color-paper)" }}>{c.t}</div>
              <div className="text-[12px]" style={{ color: "var(--color-paper-faint)" }}>{c.s}</div>
            </SpineCard>
          ))}

          {/* the bridge: past experience → future decisions */}
          <SpineCard tone="memory">
            <div className="flex items-start gap-2.5">
              <span className="text-[14px] leading-5">🧠</span>
              <div className="flex-1">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em]" style={{ color: "var(--color-accent)" }}>OPSYN Memory</div>
                <div className="mt-0.5 text-[13px] font-medium" style={{ color: "var(--color-paper)" }}>What happened before can inform what happens next.</div>
                <div className="mt-1 text-[12px]" style={{ color: "var(--color-paper-faint)" }}>Relevant experience becomes available when the next incident occurs.</div>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: "var(--color-paper-ghost)" }}>Hindsight</span>
            </div>
          </SpineCard>

          {/* the payoff: experience reused, recovery verified */}
          <SpineCard tone="future">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px]" style={{ color: "var(--color-good)" }}>INC-0928</span>
              <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.14em]" style={{ color: "var(--color-paper-ghost)" }}>Current incident</span>
            </div>
            <div className="mt-1 text-[14px] font-medium" style={{ color: "var(--color-paper)" }}>Similar pattern — experience reused</div>
            <div className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--color-paper-faint)" }}>
              OPSYN recalled relevant past incidents, compared them with the current evidence, and selected the appropriate remediation.
            </div>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[10px]" style={{ color: "var(--color-paper-ghost)" }}>
              <span>Experience recalled</span>
              <span style={{ color: "var(--color-accent)" }}>→</span>
              <span>Evidence compared</span>
              <span style={{ color: "var(--color-accent)" }}>→</span>
              <span>Remediation selected</span>
            </div>
            <div className="mt-3 flex items-center gap-2 border-t pt-2.5 text-[12px]" style={{ borderColor: "var(--color-line)", color: "var(--color-good)" }}>
              <Dot tone="good" /> Recovery verified
            </div>
          </SpineCard>
        </div>
      </div>
    </div>
  )
}

function SpineCard({
  children,
  tone,
}: {
  children: React.ReactNode
  tone: "past" | "memory" | "future"
}) {
  const nodeColor =
    tone === "memory" ? "var(--color-accent)" : tone === "future" ? "var(--color-good)" : "var(--color-paper-ghost)"
  const border =
    tone === "memory"
      ? "rgba(141,139,246,0.4)"
      : tone === "future"
        ? "rgba(99,201,154,0.35)"
        : "var(--color-line)"
  const bg =
    tone === "memory"
      ? "rgba(141,139,246,0.08)"
      : tone === "future"
        ? "rgba(99,201,154,0.06)"
        : "var(--color-ink-850)"
  return (
    <div className="relative">
      {/* node on the spine */}
      <span
        className="absolute top-5 -left-[26px] flex h-3.5 w-3.5 items-center justify-center rounded-full"
        style={{ background: "var(--color-ink-950)" }}
      >
        <span className="h-2 w-2 rounded-full" style={{ background: nodeColor }} />
      </span>
      <div
        className="rounded-xl border p-4"
        style={{ borderColor: border, background: bg, opacity: tone === "past" ? 0.82 : 1 }}
      >
        {children}
      </div>
    </div>
  )
}

function StoryBeat({
  n,
  children,
  tone,
  label,
  last,
}: {
  n: string
  children: React.ReactNode
  tone?: "critical" | "good" | "accent"
  label?: string
  last?: boolean
}) {
  return (
    <div className="relative flex gap-5">
      <div className="relative z-10 mt-1 hidden sm:block">
        <Dot tone={tone ?? "neutral"} />
      </div>
      <div className={`flex-1 ${last ? "" : ""}`}>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[11px] uppercase tracking-[0.18em]" style={{ color: tone === "accent" ? "var(--color-accent)" : tone === "good" ? "var(--color-good)" : "var(--color-paper-faint)" }}>{n}</span>
          {label && <span className="text-[12px]" style={{ color: "var(--color-paper-ghost)" }}>· {label}</span>}
        </div>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  )
}

function MiniMetric({ k, v, tone }: { k: string; v: string; tone?: "critical" | "good" }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--color-paper-ghost)" }}>{k}</div>
      <div className="tnum mt-0.5 font-mono text-[14px]" style={{ color: tone === "critical" ? "var(--color-critical)" : tone === "good" ? "var(--color-good)" : "var(--color-paper-dim)" }}>{v}</div>
    </div>
  )
}

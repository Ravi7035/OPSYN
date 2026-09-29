// Shared UI shapes plus the static narrative content still rendered by
// the Overview hero only. Incident, memory, and investigation views are
// fully backend-driven and consume nothing from this file's data.

export type Signal = {
  label: string
  value: string
  /** 0–1 fill for the meter; omit for non-metered facts */
  fill?: number
  tone?: "critical" | "good" | "neutral"
}

/* Overview narrative content (static hero copy) --------------------------- */

export const orgStats = [
  { value: "24", label: "incidents remembered" },
  { value: "17", label: "successful remediations" },
  { value: "5", label: "failed approaches remembered" },
  { value: "9", label: "recurring patterns" },
]

export type RecentIncident = {
  title: string
  status: "Resolved" | "Resolved · rollback"
  when: string
  discovered: string
  action: string
  outcome: string
  lesson: string
}

export const recentIncidents: RecentIncident[] = [
  {
    title: "Database Pool Exhaustion",
    status: "Resolved",
    when: "18 days ago",
    discovered: "DB saturation caused elevated latency across the Payment API.",
    action: "Cleared stale connections.",
    outcome: "Recovered in 43 seconds.",
    lesson:
      "Investigate stale connections before restarting when deployment is unchanged.",
  },
  {
    title: "Checkout Release Regression",
    status: "Resolved · rollback",
    when: "5 weeks ago",
    discovered: "Errors climbed within minutes of a deploy; infra stayed healthy.",
    action: "Rolled back to the previous release.",
    outcome: "Baseline restored in under a minute.",
    lesson: "A spike right after a deploy points to the release, not the infra.",
  },
  {
    title: "Redis Eviction Storm",
    status: "Resolved",
    when: "6 weeks ago",
    discovered: "Cache hit rate collapsed as memory pressure forced evictions.",
    action: "Raised the eviction threshold and warmed the cache.",
    outcome: "Latency normalized within 90 seconds.",
    lesson: "Watch eviction rate, not just hit rate, during traffic surges.",
  },
  {
    title: "Upstream Timeout Cascade",
    status: "Resolved",
    when: "2 months ago",
    discovered: "A slow dependency propagated timeouts into the Orders service.",
    action: "Tightened the client timeout and shed non-critical calls.",
    outcome: "Cascade contained in 2 minutes.",
    lesson: "Bound timeouts on every upstream call to stop failure propagation.",
  },
]

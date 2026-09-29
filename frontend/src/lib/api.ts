// Thin client for the OPSYN FastAPI backend.
//
// The backend is the source of truth for simulator state, observations,
// Hindsight recall, reasoning, actions, verification, and learning.
// This module performs no diagnosis itself: it only transports requests
// and typed responses. Base URL defaults to the local backend; override
// with VITE_API_BASE_URL for other environments.

const BASE_URL =
  (import.meta as unknown as { env?: Record<string, string | undefined> }).env
    ?.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

export class BackendError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    })
  } catch {
    throw new BackendError(
      `Cannot reach the OPSYN backend at ${BASE_URL}. Is the FastAPI server running?`,
      0,
    )
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      /* keep status text */
    }
    throw new BackendError(detail, response.status)
  }
  return (await response.json()) as T
}

/* ------------------------------- types ---------------------------------- */

export type Health = {
  service: string
  environment: string
  status: string
}

export type MetricSnapshot = Record<string, number | string>

export type SystemState = {
  service: string
  status: string
  deployment: { version: string; status: string }
  db_pool: { used: number; limit: number; status: string }
  redis: { status: string }
  queue: { depth: number; status: string }
  disk: { utilization_percent: number; status: string }
}

export type Snapshot = {
  health: Health
  metrics: MetricSnapshot
  state: SystemState
  logs: string[]
}

export type LogsResponse = {
  service: string
  logs: string[]
}

export type Memory = {
  text: string
  score: number | null
  metadata: Record<string, string> | null
}

export type RecallResponse = {
  bank_id: string
  query: string
  recall_count: number
  memories: Memory[]
}

export type Hypothesis = {
  statement: string
  status: string
  confidence: number | null
  supporting: string[]
  contradicting: string[]
}

export type InvestigationStep = {
  step_id: string
  started_at: string
  tool: string
  target: string | null
  result_summary: string
  result_refs: string[]
}

export type AgentActionRecord = {
  action_id: string
  action: string
  target: string | null
  parameters: Record<string, string | number>
  status: string
  executed_at: string | null
  result: string | null
}

export type Verification = {
  metrics_before: Record<string, number>
  metrics_after: Record<string, number>
  improved: boolean | null
  status: string
}

export type Learning = {
  outcome: string | null
  successful_actions: string[]
  failed_actions: string[]
  lesson: string | null
  suitable_for_hindsight: boolean
}

export type AgentRunResult = {
  incident_id: string
  incident_record_id: string | null
  outcome: string | null
  hypotheses: Hypothesis[]
  investigation: InvestigationStep[]
  actions: AgentActionRecord[]
  verification: Verification | null
  learning: Learning | null
  incident: Record<string, unknown>
}

export type ToolRegistry = {
  observation_tools: string[]
  action_tools: string[]
}

export type StageEvent = {
  stage: string
  at: string
}

export type IncidentRecord = {
  incident_id: string
  agent_incident_id: string | null
  service: string
  title: string
  injected_fault_type: string | null
  status: string
  created_at: string
  started_at: string
  resolved_at: string | null
  current_stage: string
  stage_history: StageEvent[]
  detected_symptoms: string[]
  diagnosis: string | null
  selected_action: string | null
  action_result: string | null
  verification_result: {
    improved?: boolean | null
    status?: string
    metrics_before?: Record<string, number>
    metrics_after?: Record<string, number>
  }
  recalled_memory_count: number
  recalled_memory_ids: string[]
  learning_outcome: string | null
  learning_lesson: string | null
  suitable_for_hindsight: boolean
  trace: {
    hypotheses?: Hypothesis[]
    investigation?: InvestigationStep[]
    actions?: AgentActionRecord[]
    verification?: Verification | null
    learning?: Learning | null
  }
}

/* ------------------------------ scenarios ------------------------------- */

export type Scenario = {
  /** fault id sent to POST /api/simulator/faults/{id} (operator action) */
  fault: string
  /** operator-facing label; never shown to the agent */
  label: string
  blurb: string
}

/** Exactly the failure modes supported by the backend simulator. */
export const SCENARIOS: Scenario[] = [
  {
    fault: "db_pool_exhaustion",
    label: "Database Pool Exhaustion",
    blurb: "Connections saturate while traffic looks normal.",
  },
  {
    fault: "bad_deployment",
    label: "Bad Deployment",
    blurb: "A fresh release starts failing requests.",
  },
  {
    fault: "memory_leak",
    label: "Memory Leak",
    blurb: "Memory climbs steadily until requests time out.",
  },
  {
    fault: "redis_failure",
    label: "Redis Failure",
    blurb: "Cache goes dark and the database absorbs the load.",
  },
  {
    fault: "dependency_timeout",
    label: "Dependency Timeout",
    blurb: "A downstream call stops answering in time.",
  },
  {
    fault: "traffic_spike",
    label: "Traffic Spike",
    blurb: "A surge of requests overwhelms capacity.",
  },
  {
    fault: "cache_stampede",
    label: "Cache Stampede",
    blurb: "Degraded cache funnels a thundering herd at the database.",
  },
  {
    fault: "disk_exhaustion",
    label: "Disk Exhaustion",
    blurb: "The volume fills and writes start failing.",
  },
]

/* -------------------------------- calls ----------------------------------- */

export function checkBackend(): Promise<{ status: string }> {
  return request<{ status: string }>("/health")
}

export function injectFault(fault: string): Promise<{ status: string }> {
  return request(`/api/simulator/faults/${fault}`, { method: "POST" })
}

export function resetSystem(): Promise<{ status: string }> {
  return request("/api/simulator/reset", { method: "POST" })
}

export function getSnapshot(): Promise<Snapshot> {
  return request<Snapshot>("/api/simulator/snapshot")
}

export function getLogs(limit = 50): Promise<LogsResponse> {
  return request<LogsResponse>(`/api/simulator/logs?limit=${limit}`)
}

export function recallMemories(query: string): Promise<RecallResponse> {
  return request<RecallResponse>("/memory/recall", {
    method: "POST",
    body: JSON.stringify({ query, max_tokens: 4096 }),
  })
}

export function runAgent(options: {
  incidentId?: string
  incidentRecordId?: string
}): Promise<AgentRunResult> {
  const body: Record<string, string> = { service: "payment-api" }
  if (options.incidentId) body.incident_id = options.incidentId
  if (options.incidentRecordId) body.incident_record_id = options.incidentRecordId
  return request<AgentRunResult>("/api/agent/run", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export function createIncident(fault: string): Promise<IncidentRecord> {
  return request<IncidentRecord>("/api/incidents", {
    method: "POST",
    body: JSON.stringify({ fault_type: fault, service: "payment-api" }),
  })
}

export function listIncidents(): Promise<{ incidents: IncidentRecord[]; count: number }> {
  return request<{ incidents: IncidentRecord[]; count: number }>("/api/incidents")
}

export function getIncident(incidentId: string): Promise<IncidentRecord> {
  return request<IncidentRecord>(`/api/incidents/${incidentId}`)
}

export function getTools(): Promise<ToolRegistry> {
  return request<ToolRegistry>("/api/agent/tools")
}

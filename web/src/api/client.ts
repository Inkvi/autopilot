export interface AutomationSummary {
  name: string
  backend: string
  model: string | null
  schedule: string
  working_directory: string | null
  last_run: string | null
  last_status: string | null
  next_run: string | null
  is_running: boolean
}

export interface AutomationDetail extends AutomationSummary {
  repos: string[]
  timeout_seconds: number
  max_retries: number
  prompt: string
  reasoning_effort: string | null
  skip_permissions: boolean
  max_turns: number
  copy_files: string[]
  run_if: { command: string; pattern?: string } | null
}

export interface RunMeta {
  timestamp: string
  status: string
  duration_s: number | null
  cost_usd: number | null
  tokens_in: number | null
  tokens_out: number | null
  started_at: string | null
  ended_at: string | null
  error: string | null
  backend: string | null
  model: string | null
}

export interface ResultList {
  automation: string
  runs: RunMeta[]
}

export interface ResultDetail {
  meta: RunMeta
  output: string
}

const BASE = ''

export async function fetchAutomations(): Promise<AutomationSummary[]> {
  const res = await fetch(`${BASE}/api/automations`)
  if (!res.ok) throw new Error(`Failed to fetch automations: ${res.status}`)
  return res.json()
}

export async function fetchAutomation(name: string): Promise<AutomationDetail> {
  const res = await fetch(`${BASE}/api/automations/${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Failed to fetch automation: ${res.status}`)
  return res.json()
}

export async function triggerRun(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/automations/${encodeURIComponent(name)}/run`, {
    method: 'POST',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Failed to trigger run: ${res.status}`)
  }
}

export async function fetchResults(name: string, limit = 50): Promise<ResultList> {
  const res = await fetch(`${BASE}/api/results/${encodeURIComponent(name)}?limit=${limit}`)
  if (!res.ok) throw new Error(`Failed to fetch results: ${res.status}`)
  return res.json()
}

export async function fetchResult(name: string, ts: string): Promise<ResultDetail> {
  const res = await fetch(
    `${BASE}/api/results/${encodeURIComponent(name)}/${encodeURIComponent(ts)}`
  )
  if (!res.ok) throw new Error(`Failed to fetch result: ${res.status}`)
  return res.json()
}

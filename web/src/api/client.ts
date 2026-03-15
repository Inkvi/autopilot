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
  output_preview: string | null
}

export interface ResultList {
  automation: string
  runs: RunMeta[]
}

export interface ResultDetail {
  meta: RunMeta
  output: string
  has_conversation: boolean
}

export interface ConversationData {
  events: ConversationEvent[]
}

export interface ConversationEvent {
  type: string  // "system" | "assistant" | "user" | "tool" | "result" | "rate_limit_event"
  subtype?: string
  message?: {
    id?: string
    content: ContentBlock[]
  }
  tool_use_id?: string
  content?: ContentBlock[]
  result?: string
  cost_usd?: number
  total_cost_usd?: number
  duration_ms?: number
  num_turns?: number
  is_error?: boolean
  tool_use_result?: {
    stdout?: string
    stderr?: string
  }
  [key: string]: unknown
}

export interface ContentBlock {
  type: string  // "text" | "tool_use" | "tool_result" | "thinking"
  text?: string
  thinking?: string
  name?: string
  input?: Record<string, unknown>
  id?: string
  tool_use_id?: string
  content?: string
  is_error?: boolean
  [key: string]: unknown
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

export async function stopRun(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/automations/${encodeURIComponent(name)}/stop`, {
    method: 'POST',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Failed to stop run: ${res.status}`)
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

export interface LiveLogData {
  events: ConversationEvent[]
  next_offset: number
  running: boolean
}

export async function fetchLiveLog(name: string, offset: number = 0): Promise<LiveLogData> {
  const res = await fetch(
    `${BASE}/api/results/${encodeURIComponent(name)}/live?offset=${offset}`
  )
  if (!res.ok) {
    if (res.status === 404) return { events: [], next_offset: offset, running: false }
    throw new Error(`Failed to fetch live log: ${res.status}`)
  }
  return res.json()
}

export async function fetchConversation(name: string, ts: string): Promise<ConversationData> {
  const res = await fetch(
    `${BASE}/api/results/${encodeURIComponent(name)}/${encodeURIComponent(ts)}/conversation`
  )
  if (!res.ok) throw new Error(`Failed to fetch conversation: ${res.status}`)
  return res.json()
}

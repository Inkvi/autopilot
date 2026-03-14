import { useState, useMemo } from 'react'
import { MarkdownRenderer } from './MarkdownRenderer'
import type { ConversationEvent } from '../api/client'

interface Props {
  events: ConversationEvent[]
}

// A normalized step for rendering
interface Step {
  kind: 'text' | 'tool_use' | 'tool_result' | 'thinking' | 'result'
  text?: string
  toolName?: string
  toolInput?: string
  toolOutput?: string
  isError?: boolean
  cost?: number
  durationMs?: number
  numTurns?: number
}

function useSteps(events: ConversationEvent[]): Step[] {
  return useMemo(() => {
    const steps: Step[] = []

    for (const event of events) {
      // Skip noise: system events (hooks, init), rate_limit_event, thread/turn lifecycle
      if (event.type === 'system' || event.type === 'rate_limit_event') continue
      if (event.type === 'thread.started' || event.type === 'turn.started') continue

      // --- Codex CLI format ---
      // item.completed with item.type "agent_message" = assistant text
      // item.completed with item.type "command_execution" = tool use + result
      // item.started with item.type "command_execution" = tool started (skip, wait for completed)
      // turn.completed = usage info
      if (event.type === 'item.started') continue
      if (event.type === 'item.completed') {
        const item = (event as Record<string, unknown>).item as Record<string, unknown> | undefined
        if (!item) continue
        if (item.type === 'agent_message' && typeof item.text === 'string' && item.text.trim()) {
          steps.push({ kind: 'text', text: item.text })
        } else if (item.type === 'command_execution') {
          const cmd = typeof item.command === 'string' ? item.command : ''
          const output = typeof item.aggregated_output === 'string' ? item.aggregated_output : ''
          const exitCode = typeof item.exit_code === 'number' ? item.exit_code : null
          steps.push({ kind: 'tool_use', toolName: 'Shell', toolInput: cmd })
          if (output || exitCode !== null) {
            const outputText = exitCode !== null && exitCode !== 0
              ? `${output}\n[exit code: ${exitCode}]`
              : output
            steps.push({ kind: 'tool_result', toolOutput: outputText, isError: exitCode !== 0 && exitCode !== null })
          }
        } else if (item.type === 'error' && typeof item.message === 'string') {
          steps.push({ kind: 'tool_result', toolOutput: item.message, isError: true })
        }
        continue
      }
      if (event.type === 'turn.completed') {
        // Codex turn summary with usage — we show it as a subtle result
        const u = (event as Record<string, unknown>).usage as Record<string, unknown> | undefined
        if (u) {
          steps.push({
            kind: 'result',
            numTurns: undefined,
            cost: undefined,
          })
        }
        continue
      }
      if (event.type === 'turn.failed') {
        const err = (event as Record<string, unknown>).error as Record<string, unknown> | undefined
        const msg = typeof err?.message === 'string' ? err.message : 'Turn failed'
        steps.push({ kind: 'tool_result', toolOutput: msg, isError: true })
        continue
      }
      if (event.type === 'error') {
        const msg = typeof (event as Record<string, unknown>).message === 'string'
          ? (event as Record<string, unknown>).message as string
          : 'Unknown error'
        steps.push({ kind: 'tool_result', toolOutput: msg, isError: true })
        continue
      }

      // --- Claude CLI format ---
      if (event.type === 'assistant') {
        const blocks = event.message?.content ?? []
        for (const block of blocks) {
          if (block.type === 'text' && block.text?.trim()) {
            steps.push({ kind: 'text', text: block.text })
          } else if (block.type === 'tool_use') {
            const input = block.input
              ? (typeof block.input === 'string' ? block.input : JSON.stringify(block.input, null, 2))
              : undefined
            steps.push({ kind: 'tool_use', toolName: block.name ?? 'unknown', toolInput: input })
          } else if (block.type === 'thinking') {
            // thinking blocks use "thinking" field, not "text"
            const text = block.thinking || block.text
            if (text?.trim()) {
              steps.push({ kind: 'thinking', text })
            }
          }
        }
      }

      // Tool results come as type:"user" in CLI stream-json
      if (event.type === 'user') {
        const blocks = event.message?.content ?? event.content ?? []
        for (const block of blocks) {
          if (block.type === 'tool_result') {
            const output = typeof block.content === 'string'
              ? block.content
              : block.text ?? ''
            steps.push({
              kind: 'tool_result',
              toolOutput: output,
              isError: block.is_error === true,
            })
          }
        }
        // Also check tool_use_result (CLI-specific field on the event)
        const tur = event.tool_use_result
        if (tur) {
          const lastStep = steps[steps.length - 1]
          if (lastStep?.kind === 'tool_result' && !lastStep.toolOutput && tur.stdout) {
            lastStep.toolOutput = tur.stdout
          }
        }
      }

      // Also handle type:"tool" (SDK format)
      if (event.type === 'tool') {
        const blocks = event.content ?? []
        const output = Array.isArray(blocks)
          ? blocks.map((b) => b.text || b.content || '').filter(Boolean).join('\n')
          : typeof blocks === 'string' ? blocks : ''
        if (output) {
          steps.push({ kind: 'tool_result', toolOutput: output })
        }
      }

      if (event.type === 'result') {
        steps.push({
          kind: 'result',
          text: event.result ?? '',
          cost: (event.total_cost_usd ?? event.cost_usd) as number | undefined,
          durationMs: event.duration_ms,
          numTurns: event.num_turns,
        })
      }
    }
    return steps
  }, [events])
}

function CollapsibleBlock({ label, content, defaultOpen = false, maxPreviewLines = 3 }: {
  label: string
  content: string
  defaultOpen?: boolean
  maxPreviewLines?: number
}) {
  const [expanded, setExpanded] = useState(defaultOpen)
  if (!content) return null

  const lines = content.split('\n')
  const hasMore = lines.length > maxPreviewLines

  return (
    <div className="conv-collapsible">
      <button className="conv-toggle" onClick={() => setExpanded(!expanded)}>
        {expanded ? `- Hide ${label}` : `+ Show ${label} (${lines.length} lines)`}
      </button>
      {expanded && <pre className="conv-pre">{content}</pre>}
      {!expanded && (
        <pre className="conv-pre conv-preview">
          {hasMore ? lines.slice(0, maxPreviewLines).join('\n') + '\n...' : content}
        </pre>
      )}
    </div>
  )
}

export function ConversationView({ events }: Props) {
  const steps = useSteps(events)

  if (steps.length === 0) {
    return <div className="text-muted">No conversation steps recorded.</div>
  }

  return (
    <div className="conv-timeline">
      {steps.map((step, i) => {
        if (step.kind === 'text') {
          return (
            <div key={i} className="conv-step conv-step-assistant">
              <div className="conv-step-marker">
                <span className="conv-dot conv-dot-assistant" />
                <span className="conv-step-label">Assistant</span>
              </div>
              <div className="conv-step-body">
                <div className="conv-text">
                  <MarkdownRenderer content={step.text!} />
                </div>
              </div>
            </div>
          )
        }

        if (step.kind === 'tool_use') {
          return (
            <div key={i} className="conv-step conv-step-tool-use">
              <div className="conv-step-marker">
                <span className="conv-dot conv-dot-tool-use" />
                <span className="conv-step-label">Tool</span>
              </div>
              <div className="conv-step-body">
                <div className="conv-tool-use">
                  <div className="conv-tool-header">
                    <span className="conv-tool-name">{step.toolName}</span>
                  </div>
                  {step.toolInput && <CollapsibleBlock label="input" content={step.toolInput} />}
                </div>
              </div>
            </div>
          )
        }

        if (step.kind === 'tool_result') {
          return (
            <div key={i} className="conv-step conv-step-tool-result">
              <div className="conv-step-marker">
                <span className={`conv-dot ${step.isError ? 'conv-dot-error' : 'conv-dot-tool-result'}`} />
                <span className="conv-step-label">{step.isError ? 'Error' : 'Output'}</span>
              </div>
              <div className="conv-step-body">
                {step.toolOutput && (
                  <CollapsibleBlock label="output" content={step.toolOutput} />
                )}
                {!step.toolOutput && (
                  <span className="text-muted">(empty)</span>
                )}
              </div>
            </div>
          )
        }

        if (step.kind === 'thinking') {
          return (
            <div key={i} className="conv-step conv-step-thinking">
              <div className="conv-step-marker">
                <span className="conv-dot conv-dot-thinking" />
                <span className="conv-step-label">Thinking</span>
              </div>
              <div className="conv-step-body">
                <CollapsibleBlock label="thinking" content={step.text!} />
              </div>
            </div>
          )
        }

        if (step.kind === 'result') {
          return (
            <div key={i} className="conv-step conv-step-result">
              <div className="conv-step-marker">
                <span className="conv-dot conv-dot-result" />
                <span className="conv-step-label">Result</span>
              </div>
              <div className="conv-step-body">
                {(step.cost != null || step.durationMs != null || step.numTurns != null) && (
                  <div className="conv-result-meta">
                    {step.cost != null && <span>Cost: ${step.cost.toFixed(4)}</span>}
                    {step.durationMs != null && <span>Duration: {(step.durationMs / 1000).toFixed(1)}s</span>}
                    {step.numTurns != null && <span>Turns: {step.numTurns}</span>}
                  </div>
                )}
              </div>
            </div>
          )
        }

        return null
      })}
    </div>
  )
}

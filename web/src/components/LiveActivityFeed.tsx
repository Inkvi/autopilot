import { useMemo } from 'react'
import type { ConversationEvent } from '../api/client'

interface Props {
  events: ConversationEvent[]
}

// A compact line item for the activity feed
interface ActivityLine {
  kind: 'thinking' | 'text' | 'tool' | 'tool_done' | 'error'
  content: string
  lines?: number
  isError?: boolean
}

function summarizeInput(input: Record<string, unknown> | undefined, toolName: string): string {
  if (!input) return ''
  // Extract the most useful field for a one-line summary
  if (toolName === 'Bash' || toolName === 'Shell') {
    const cmd = input.command as string || ''
    // Trim long commands
    return cmd.length > 100 ? cmd.slice(0, 97) + '...' : cmd
  }
  if (toolName === 'Read') {
    const fp = input.file_path as string || ''
    // Show just filename, not full tmp path
    const short = fp.replace(/.*\/worktree\//, '').replace(/.*\/autopilot-run-[^/]*\//, '')
    return short || fp
  }
  if (toolName === 'Write' || toolName === 'Edit') {
    const fp = (input.file_path as string) || ''
    const short = fp.replace(/.*\/worktree\//, '').replace(/.*\/autopilot-run-[^/]*\//, '')
    return short || fp
  }
  if (toolName === 'Grep') {
    return (input.pattern as string) || ''
  }
  if (toolName === 'Glob') {
    return (input.pattern as string) || ''
  }
  if (toolName === 'Agent') {
    return (input.description as string) || (input.prompt as string)?.slice(0, 60) || ''
  }
  if (toolName === 'WebSearch') {
    return (input.query as string) || ''
  }
  if (toolName === 'WebFetch') {
    return (input.url as string) || ''
  }
  // Fallback: show first string value
  for (const v of Object.values(input)) {
    if (typeof v === 'string' && v.trim()) {
      return v.length > 80 ? v.slice(0, 77) + '...' : v
    }
  }
  return ''
}

function countLines(text: string | undefined): number | undefined {
  if (!text) return undefined
  return text.split('\n').length
}

function useActivityLines(events: ConversationEvent[]): ActivityLine[] {
  return useMemo(() => {
    const lines: ActivityLine[] = []

    for (const event of events) {
      // Skip noise
      if (event.type === 'system' || event.type === 'rate_limit_event') continue
      if (event.type === 'thread.started' || event.type === 'turn.started') continue
      if (event.type === 'item.started') continue

      // --- Claude CLI format ---
      if (event.type === 'assistant') {
        const blocks = event.message?.content ?? []
        for (const block of blocks) {
          if (block.type === 'thinking') {
            const text = block.thinking || block.text || ''
            if (text.trim()) {
              lines.push({ kind: 'thinking', content: text.trim() })
            }
          } else if (block.type === 'text' && block.text?.trim()) {
            lines.push({ kind: 'text', content: block.text.trim() })
          } else if (block.type === 'tool_use') {
            const name = block.name ?? 'Tool'
            const summary = summarizeInput(block.input, name)
            lines.push({ kind: 'tool', content: summary ? `${name}: ${summary}` : name })
          }
        }
      }

      if (event.type === 'user') {
        const blocks = event.message?.content ?? event.content ?? []
        for (const block of blocks) {
          if (block.type === 'tool_result') {
            const output = typeof block.content === 'string' ? block.content : block.text ?? ''
            const lc = countLines(output)
            const isErr = block.is_error === true
            if (isErr) {
              const preview = output.split('\n')[0]?.slice(0, 80) || 'error'
              lines.push({ kind: 'error', content: preview, isError: true })
            } else if (lc) {
              lines.push({ kind: 'tool_done', content: `${lc} lines`, lines: lc })
            }
          }
        }
      }

      // --- Codex CLI format ---
      if (event.type === 'item.completed') {
        const item = event.item as Record<string, unknown> | undefined
        if (!item) continue
        if (item.type === 'agent_message' && typeof item.text === 'string' && item.text.trim()) {
          lines.push({ kind: 'text', content: item.text.trim() })
        } else if (item.type === 'command_execution') {
          const cmd = typeof item.command === 'string' ? item.command : ''
          // Strip shell wrapper prefix
          const short = cmd.replace(/^\/bin\/(zsh|bash)\s+-lc\s+'?/, '').replace(/'$/, '')
          lines.push({ kind: 'tool', content: `Shell: ${short.length > 100 ? short.slice(0, 97) + '...' : short}` })
          const output = typeof item.aggregated_output === 'string' ? item.aggregated_output : ''
          const exitCode = typeof item.exit_code === 'number' ? item.exit_code : null
          if (exitCode !== null && exitCode !== 0) {
            lines.push({ kind: 'error', content: `exit code ${exitCode}`, isError: true })
          } else {
            const lc = countLines(output)
            if (lc) {
              lines.push({ kind: 'tool_done', content: `${lc} lines` })
            }
          }
        } else if (item.type === 'error' && typeof item.message === 'string') {
          lines.push({ kind: 'error', content: item.message.slice(0, 100), isError: true })
        }
      }

      if (event.type === 'turn.failed') {
        const err = event.error as Record<string, unknown> | undefined
        const msg = typeof err?.message === 'string' ? err.message : 'Turn failed'
        lines.push({ kind: 'error', content: msg.slice(0, 100), isError: true })
      }

      if (event.type === 'result') {
        // Skip result in live feed — run is about to finish
      }
    }
    return lines
  }, [events])
}

/** Quick check if events contain any visible activity lines. */
export function hasVisibleLines(events: ConversationEvent[]): boolean {
  for (const event of events) {
    if (event.type === 'assistant') {
      const blocks = event.message?.content ?? []
      if (blocks.some((b) => b.type === 'text' || b.type === 'tool_use' || b.type === 'thinking')) return true
    }
    if (event.type === 'user' || event.type === 'item.completed' || event.type === 'turn.failed') return true
  }
  return false
}

export function LiveActivityFeed({ events }: Props) {
  const lines = useActivityLines(events)

  if (lines.length === 0) return null

  return (
    <div className="activity-feed">
      {lines.map((line, i) => {
        if (line.kind === 'thinking') {
          return (
            <div key={i} className="activity-line activity-thinking">
              <span className="activity-icon">~</span>
              <span className="activity-content">{line.content}</span>
            </div>
          )
        }
        if (line.kind === 'text') {
          // Truncate long assistant text to first 2 lines
          const truncated = line.content.split('\n').slice(0, 2).join(' ')
          const display = truncated.length > 200 ? truncated.slice(0, 197) + '...' : truncated
          return (
            <div key={i} className="activity-line activity-text">
              <span className="activity-content activity-assistant-text">{display}</span>
            </div>
          )
        }
        if (line.kind === 'tool') {
          return (
            <div key={i} className="activity-line activity-tool">
              <span className="activity-icon">→</span>
              <span className="activity-content">{line.content}</span>
            </div>
          )
        }
        if (line.kind === 'tool_done') {
          return (
            <div key={i} className="activity-line activity-tool-done">
              <span className="activity-icon">✓</span>
              <span className="activity-content">{line.content}</span>
            </div>
          )
        }
        if (line.kind === 'error') {
          return (
            <div key={i} className="activity-line activity-error">
              <span className="activity-icon">✗</span>
              <span className="activity-content">{line.content}</span>
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

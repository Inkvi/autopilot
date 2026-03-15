import type { ConversationEvent } from '../api/client'

/**
 * Format conversation events as readable plain text for clipboard copy.
 */
export function formatConversationAsText(events: ConversationEvent[]): string {
  const lines: string[] = []

  for (const event of events) {
    if (event.type === 'system' || event.type === 'rate_limit_event') continue
    if (event.type === 'thread.started' || event.type === 'turn.started') continue
    if (event.type === 'item.started') continue

    // Claude CLI format
    if (event.type === 'assistant') {
      const blocks = event.message?.content ?? []
      for (const block of blocks) {
        if (block.type === 'thinking') {
          const text = block.thinking || block.text || ''
          if (text.trim()) {
            lines.push(`[thinking] ${text.trim()}`)
            lines.push('')
          }
        } else if (block.type === 'text' && block.text?.trim()) {
          lines.push(block.text.trim())
          lines.push('')
        } else if (block.type === 'tool_use') {
          const name = block.name ?? 'Tool'
          const input = block.input
            ? (typeof block.input === 'string' ? block.input : JSON.stringify(block.input, null, 2))
            : ''
          lines.push(`[Tool Call | ${name}]`)
          if (input) {
            lines.push(input)
          }
          lines.push('')
        }
      }
    }

    // Tool results (Claude CLI)
    if (event.type === 'user') {
      const blocks = event.message?.content ?? event.content ?? []
      for (const block of blocks) {
        if (block.type === 'tool_result') {
          const output = typeof block.content === 'string' ? block.content : block.text ?? ''
          lines.push('[Tool Response]')
          lines.push(output || '(empty)')
          lines.push('')
        }
      }
    }

    // SDK format
    if (event.type === 'tool') {
      const blocks = event.content ?? []
      const output = Array.isArray(blocks)
        ? blocks.map((b) => b.text || b.content || '').filter(Boolean).join('\n')
        : typeof blocks === 'string' ? blocks : ''
      lines.push('[Tool Response]')
      lines.push(output || '(empty)')
      lines.push('')
    }

    // Codex CLI format
    if (event.type === 'item.completed') {
      const item = event.item as Record<string, unknown> | undefined
      if (!item) continue
      if (item.type === 'agent_message' && typeof item.text === 'string' && item.text.trim()) {
        lines.push(item.text.trim())
        lines.push('')
      } else if (item.type === 'command_execution') {
        const cmd = typeof item.command === 'string' ? item.command : ''
        const output = typeof item.aggregated_output === 'string' ? item.aggregated_output : ''
        lines.push(`[Tool Call | Shell] ${cmd}`)
        lines.push('[Tool Response]')
        lines.push(output || '(empty)')
        lines.push('')
      } else if (item.type === 'error' && typeof item.message === 'string') {
        lines.push(`[error] ${item.message}`)
        lines.push('')
      }
    }

    if (event.type === 'result') {
      const cost = (event.total_cost_usd ?? event.cost_usd) as number | undefined
      if (cost != null || event.duration_ms != null) {
        const parts: string[] = []
        if (cost != null) parts.push(`Cost: $${cost.toFixed(4)}`)
        if (event.duration_ms != null) parts.push(`Duration: ${(event.duration_ms / 1000).toFixed(1)}s`)
        if (event.num_turns != null) parts.push(`Turns: ${event.num_turns}`)
        lines.push(`--- ${parts.join(' | ')} ---`)
        lines.push('')
      }
      if (event.result) {
        lines.push(event.result)
      }
    }
  }

  return lines.join('\n').trim()
}

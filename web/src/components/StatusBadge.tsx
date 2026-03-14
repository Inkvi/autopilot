interface StatusBadgeProps {
  status: string | null
  isRunning?: boolean
}

const STATUS_STYLES: Record<string, { color: string; bg: string; label: string; glow?: string }> = {
  ok: { color: '#34d399', bg: 'rgba(52,211,153,0.08)', label: 'ok', glow: 'rgba(52,211,153,0.3)' },
  error: { color: '#f87171', bg: 'rgba(248,113,113,0.08)', label: 'error' },
  running: { color: '#fbbf24', bg: 'rgba(251,191,36,0.08)', label: 'running', glow: 'rgba(251,191,36,0.3)' },
  idle: { color: '#505872', bg: 'rgba(80,88,114,0.08)', label: 'idle' },
}

export function StatusBadge({ status, isRunning }: StatusBadgeProps) {
  const key = isRunning ? 'running' : (status ?? 'idle')
  const style = STATUS_STYLES[key] || STATUS_STYLES.idle

  return (
    <span
      style={{
        color: style.color,
        background: style.bg,
        padding: '3px 10px',
        borderRadius: '100px',
        fontSize: '11px',
        fontFamily: "'JetBrains Mono', monospace",
        fontWeight: 400,
        letterSpacing: '0.02em',
        border: `1px solid ${style.color}20`,
        display: 'inline-flex',
        alignItems: 'center',
        gap: '5px',
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: '50%',
          background: style.color,
          boxShadow: style.glow ? `0 0 6px ${style.glow}` : undefined,
          flexShrink: 0,
        }}
      />
      {style.label}
    </span>
  )
}

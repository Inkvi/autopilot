import { useEffect, useState } from 'react'

export interface ToastMessage {
  id: number
  type: 'success' | 'error'
  text: string
}

let nextId = 0

// Simple module-level state shared via hook
const listeners = new Set<() => void>()
let toasts: ToastMessage[] = []

function notify() {
  listeners.forEach((l) => l())
}

export function showToast(type: 'success' | 'error', text: string) {
  const id = nextId++
  toasts = [...toasts, { id, type, text }]
  notify()
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id)
    notify()
  }, 4000)
}

export function useToasts(): ToastMessage[] {
  const [, setTick] = useState(0)
  useEffect(() => {
    const cb = () => setTick((t) => t + 1)
    listeners.add(cb)
    return () => { listeners.delete(cb) }
  }, [])
  return toasts
}

export function ToastContainer() {
  const items = useToasts()

  return (
    <div style={{
      position: 'fixed',
      bottom: 20,
      right: 20,
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
    }}>
      {items.map((t) => (
        <div
          key={t.id}
          style={{
            padding: '10px 16px',
            borderRadius: 8,
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 400,
            animation: 'fadeInUp 0.3s ease-out',
            background: t.type === 'success'
              ? 'rgba(52, 211, 153, 0.1)'
              : 'rgba(248, 113, 113, 0.1)',
            border: `1px solid ${t.type === 'success'
              ? 'rgba(52, 211, 153, 0.2)'
              : 'rgba(248, 113, 113, 0.2)'}`,
            color: t.type === 'success' ? '#34d399' : '#f87171',
            backdropFilter: 'blur(12px)',
            boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: t.type === 'success' ? '#34d399' : '#f87171',
            flexShrink: 0,
          }} />
          {t.text}
        </div>
      ))}
    </div>
  )
}

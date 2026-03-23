import { useParams, Link, useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState, useCallback } from 'react'
import { fetchLiveLog, fetchAutomation, stopRun } from '../api/client'
import type { ConversationEvent } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { ConversationView } from '../components/ConversationView'
import { hasVisibleLines } from '../components/LiveActivityFeed'
import { StatusBadge } from '../components/StatusBadge'
import { ElapsedTimer } from '../components/ElapsedTimer'
import { CopyButton } from '../components/CopyButton'
import { showToast } from '../components/Toast'
import { formatConversationAsText } from '../utils/formatConversation'

export function LiveStepsPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const [events, setEvents] = useState<ConversationEvent[]>([])
  const offsetRef = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data: automation } = usePolling(
    useCallback(() => fetchAutomation(name!), [name]),
    5000,
  )

  const isRunning = automation?.is_running ?? true
  const startTime = automation?.run_started_at ? new Date(automation.run_started_at).getTime() : null

  const poll = useCallback(async () => {
    try {
      const data = await fetchLiveLog(name!, offsetRef.current)
      if (data.events.length > 0) {
        setEvents((prev) => [...prev, ...data.events])
      }
      offsetRef.current = data.next_offset
    } catch {
      // ignore
    }
  }, [name])

  // Poll while running
  useEffect(() => {
    if (!isRunning) return
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [isRunning, poll])

  // When automation finishes, redirect to the completed result
  useEffect(() => {
    if (!isRunning && automation) {
      // Small delay to let the result be saved
      const timer = setTimeout(() => {
        navigate(`/automations/${name}`, { replace: true })
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [isRunning, automation, name, navigate])

  // Auto-scroll
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events])

  const handleStop = async () => {
    try {
      await stopRun(name!)
      showToast('success', `${name} stopped`)
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to stop')
    }
  }

  return (
    <div>
      <div className="breadcrumb">
        <Link to={`/automations/${name}`} className="link">← {name}</Link>
        <span className="text-muted"> / live</span>
      </div>

      <div className="page-header">
        <div>
          <h2>Live Steps</h2>
          <div className="text-muted text-sm" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <StatusBadge status={null} isRunning={isRunning} />
            {startTime != null && <ElapsedTimer startTime={startTime as number} />}
          </div>
        </div>
        {isRunning && (
          <button className="btn btn-danger" onClick={handleStop}>
            Stop
          </button>
        )}
        {!isRunning && (
          <span className="text-muted text-sm">Redirecting to results...</span>
        )}
      </div>

      <div className="output-container" ref={containerRef} style={{ maxHeight: '70vh', overflowY: 'auto' }}>
        {!hasVisibleLines(events) && isRunning && (
          <div className="live-waiting">
            <div className="live-waiting-dots">
              <span /><span /><span />
            </div>
            Waiting for output...
          </div>
        )}
        {hasVisibleLines(events) && (
          <>
            <div className="output-header">
              <CopyButton text={formatConversationAsText(events)} />
            </div>
            <ConversationView events={events} />
          </>
        )}
      </div>
    </div>
  )
}

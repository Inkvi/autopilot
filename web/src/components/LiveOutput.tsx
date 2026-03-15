import { useEffect, useRef, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { fetchLiveLog } from '../api/client'
import type { ConversationEvent } from '../api/client'
import { LiveActivityFeed, hasVisibleLines } from './LiveActivityFeed'

interface Props {
  name: string
  isRunning: boolean
}

export function LiveOutput({ name, isRunning }: Props) {
  const [events, setEvents] = useState<ConversationEvent[]>([])
  const offsetRef = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)

  const poll = useCallback(async () => {
    try {
      const data = await fetchLiveLog(name, offsetRef.current)
      if (data.events.length > 0) {
        setEvents((prev) => [...prev, ...data.events])
      }
      offsetRef.current = data.next_offset
    } catch {
      // Ignore fetch errors during polling
    }
  }, [name])

  // Reset when automation name changes
  useEffect(() => {
    setEvents([])
    offsetRef.current = 0
  }, [name])

  // Clear when automation finishes
  useEffect(() => {
    if (!isRunning) {
      setEvents([])
      offsetRef.current = 0
    }
  }, [isRunning])

  // Poll while running
  useEffect(() => {
    if (!isRunning) return
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [isRunning, poll])

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events])

  const hasVisible = hasVisibleLines(events)

  if (!isRunning && !hasVisible) return null

  return (
    <div className="live-output-section">
      <h3 className="section-title">
        <Link to={`/automations/${name}/live`} className="link">Live Output</Link>
        {isRunning && <span className="live-dot" />}
      </h3>
      <div className="output-container live" ref={containerRef}>
        {!hasVisible && isRunning && (
          <div className="live-waiting">
            <div className="live-waiting-dots">
              <span /><span /><span />
            </div>
            Waiting for output...
          </div>
        )}
        {hasVisible && <LiveActivityFeed events={events} />}
      </div>
    </div>
  )
}

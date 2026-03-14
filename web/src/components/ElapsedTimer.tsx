import { useState, useEffect } from 'react'

interface ElapsedTimerProps {
  startTime: number // Date.now() when started
}

export function ElapsedTimer({ startTime }: ElapsedTimerProps) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [startTime])

  return <span>{elapsed}s</span>
}

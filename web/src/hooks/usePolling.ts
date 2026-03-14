import { useEffect, useState, useCallback, useRef } from 'react'

interface UsePollingResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  refresh: () => void
  boost: (durationMs?: number, fastIntervalMs?: number) => void
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 10000,
): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeInterval, setActiveInterval] = useState(intervalMs)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const boostTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const doFetch = useCallback(async () => {
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  const boost = useCallback((durationMs = 30000, fastIntervalMs = 2000) => {
    setActiveInterval(fastIntervalMs)
    if (boostTimerRef.current) clearTimeout(boostTimerRef.current)
    boostTimerRef.current = setTimeout(() => {
      setActiveInterval(intervalMs)
      boostTimerRef.current = null
    }, durationMs)
    doFetch()
  }, [intervalMs, doFetch])

  useEffect(() => {
    doFetch()
    if (activeInterval <= 0) return
    const id = setInterval(doFetch, activeInterval)
    return () => clearInterval(id)
  }, [doFetch, activeInterval])

  useEffect(() => {
    return () => {
      if (boostTimerRef.current) clearTimeout(boostTimerRef.current)
    }
  }, [])

  return { data, loading, error, refresh: doFetch, boost }
}

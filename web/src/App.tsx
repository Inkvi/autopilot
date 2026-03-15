import { useState, useCallback, useMemo } from 'react'
import { BrowserRouter, Routes, Route, useParams } from 'react-router-dom'
import { fetchAutomations, type AutomationSummary } from './api/client'
import { usePolling } from './hooks/usePolling'
import { Sidebar } from './components/Sidebar'
import { ToastContainer } from './components/Toast'
import { AutomationListPage } from './pages/AutomationListPage'
import { AutomationDetailPage } from './pages/AutomationDetailPage'
import { ResultDetailPage } from './pages/ResultDetailPage'
import { LiveStepsPage } from './pages/LiveStepsPage'
import './App.css'

// Map of automation name → timestamp when trigger was clicked
export type TriggerMap = Map<string, number>

// Wrappers that remount child components when URL params change
function AutomationDetailWrapper(props: { onTrigger: (name: string) => void; triggers: TriggerMap }) {
  const { name } = useParams<{ name: string }>()
  return <AutomationDetailPage key={name} {...props} />
}

function ResultDetailWrapper() {
  const { name, ts } = useParams<{ name: string; ts: string }>()
  return <ResultDetailPage key={`${name}-${ts}`} />
}

function LiveStepsWrapper() {
  const { name } = useParams<{ name: string }>()
  return <LiveStepsPage key={name} />
}

export default function App() {
  const { data: automations, refresh, boost } = usePolling(fetchAutomations, 10000)
  const [triggers, setTriggers] = useState<TriggerMap>(new Map())

  const handleTrigger = useCallback((name: string) => {
    setTriggers((prev) => new Map(prev).set(name, Date.now()))
    boost()
    // Clear the optimistic flag after 30s (boost duration)
    setTimeout(() => {
      setTriggers((prev) => {
        const next = new Map(prev)
        next.delete(name)
        return next
      })
    }, 30000)
  }, [boost])

  // Derive triggered set for components that just need a boolean
  const triggeredNames = useMemo(() => new Set(triggers.keys()), [triggers])

  // Merge optimistic "running" state into automation data
  const enriched: AutomationSummary[] = useMemo(() => {
    if (!automations) return []
    return automations.map((a) =>
      triggeredNames.has(a.name) ? { ...a, is_running: true } : a
    )
  }, [automations, triggeredNames])

  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar automations={enriched} />
        <main className="main-content">
          <Routes>
            <Route
              path="/"
              element={
                <AutomationListPage
                  automations={enriched}
                  onRefresh={refresh}
                  onTrigger={handleTrigger}
                />
              }
            />
            <Route
              path="/automations/:name"
              element={<AutomationDetailWrapper onTrigger={handleTrigger} triggers={triggers} />}
            />
            <Route path="/automations/:name/live" element={<LiveStepsWrapper />} />
            <Route path="/automations/:name/results/:ts" element={<ResultDetailWrapper />} />
          </Routes>
        </main>
      </div>
      <ToastContainer />
    </BrowserRouter>
  )
}

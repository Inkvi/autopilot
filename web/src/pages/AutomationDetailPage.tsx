import { useParams, Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { fetchAutomation, fetchResults, triggerRun, stopRun } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { StatusBadge } from '../components/StatusBadge'
import { ElapsedTimer } from '../components/ElapsedTimer'
import { CopyButton } from '../components/CopyButton'
import { LiveOutput } from '../components/LiveOutput'
import { showToast } from '../components/Toast'
import { useCallback, useEffect, useRef } from 'react'
import type { TriggerMap } from '../App'

interface Props {
  onTrigger: (name: string) => void
  triggers: TriggerMap
}

export function AutomationDetailPage({ onTrigger, triggers }: Props) {
  const { name } = useParams<{ name: string }>()
  const runningRowRef = useRef<HTMLTableRowElement>(null)

  const { data: automation, boost: boostAuto } = usePolling(
    useCallback(() => fetchAutomation(name!), [name]),
    10000,
  )
  const { data: results, boost: boostResults } = usePolling(
    useCallback(() => fetchResults(name!), [name]),
    10000,
  )

  const triggerTime = triggers.get(name!)
  const isRunning = automation?.is_running || !!triggerTime

  const handleRun = async () => {
    try {
      await triggerRun(name!)
      onTrigger(name!)
      showToast('success', `${name} started`)
      boostAuto()
      boostResults()
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to trigger run')
    }
  }

  const handleStop = async () => {
    try {
      await stopRun(name!)
      showToast('success', `${name} stopped`)
      boostAuto()
      boostResults()
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to stop run')
    }
  }

  // Auto-scroll to running row (#4)
  useEffect(() => {
    if (isRunning && runningRowRef.current) {
      runningRowRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [isRunning])

  if (!automation || !results) return <div className="text-muted">Loading...</div>

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{automation.name}</h2>
          <div className="text-muted text-sm">
            {automation.backend} · {automation.model || 'default'} · every {automation.schedule}
            {automation.next_run &&
              ` · next run ${formatDistanceToNow(new Date(automation.next_run), { addSuffix: true })}`}
          </div>
        </div>
        {isRunning ? (
          <button className="btn btn-danger" onClick={handleStop}>
            Stop
          </button>
        ) : (
          <button className="btn btn-primary" onClick={handleRun}>
            Run Now
          </button>
        )}
      </div>

      <div className="config-section">
        <h3 className="section-title">Configuration</h3>
        <div className="config-grid">
          <div className="config-item">
            <span className="config-label">Backend</span>
            <span className="config-value">{automation.backend}</span>
          </div>
          <div className="config-item">
            <span className="config-label">Model</span>
            <span className="config-value">{automation.model || 'default'}</span>
          </div>
          <div className="config-item">
            <span className="config-label">Schedule</span>
            <span className="config-value">{automation.schedule}</span>
          </div>
          <div className="config-item">
            <span className="config-label">Timeout</span>
            <span className="config-value">{automation.timeout_seconds}s</span>
          </div>
          <div className="config-item">
            <span className="config-label">Max Retries</span>
            <span className="config-value">{automation.max_retries}</span>
          </div>
          <div className="config-item">
            <span className="config-label">Max Turns</span>
            <span className="config-value">{automation.max_turns}</span>
          </div>
          {automation.reasoning_effort && (
            <div className="config-item">
              <span className="config-label">Reasoning</span>
              <span className="config-value">{automation.reasoning_effort}</span>
            </div>
          )}
          {automation.working_directory && (
            <div className="config-item">
              <span className="config-label">Working Dir</span>
              <span className="config-value code">{automation.working_directory}</span>
            </div>
          )}
          {automation.run_if && (
            <div className="config-item">
              <span className="config-label">Run If</span>
              <span className="config-value code">{automation.run_if.command}</span>
            </div>
          )}
        </div>
        {automation.repos.length > 0 && (
          <div className="config-repos">
            <span className="config-label">Repos</span>
            <div className="config-repos-list">
              {automation.repos.map((repo) => {
                const repoName = repo.replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '')
                return (
                  <a key={repo} href={repo} target="_blank" rel="noopener noreferrer" className="config-repo-link">
                    {repoName}
                  </a>
                )
              })}
            </div>
          </div>
        )}
        <div className="config-prompt">
          <div className="config-prompt-header">
            <span className="config-label">Prompt</span>
            <CopyButton text={automation.prompt.trim()} />
          </div>
          <pre className="config-prompt-text">{automation.prompt.trim()}</pre>
        </div>
      </div>

      <LiveOutput name={name!} isRunning={isRunning} />

      <h3 className="section-title">Run History</h3>
      <div className="table-container">
        <table className="table">
          <thead>
            <tr>
              <th>Started</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Cost</th>
              <th>Preview</th>
            </tr>
          </thead>
          <tbody>
            {isRunning && (
              <tr className="running-row" ref={runningRowRef}>
                <td>
                  <Link to={`/automations/${name}/live`} className="link">
                    {triggerTime ? new Date(triggerTime).toLocaleString() : 'now'}
                  </Link>
                </td>
                <td>
                  <StatusBadge status={null} isRunning />
                </td>
                <td className="text-secondary">
                  {triggerTime ? <ElapsedTimer startTime={triggerTime} /> : '-'}
                </td>
                <td className="text-secondary">-</td>
                <td className="text-muted">-</td>
              </tr>
            )}
            {!isRunning && results.runs.length === 0 && (
              <tr>
                <td colSpan={5} className="text-muted">No runs yet.</td>
              </tr>
            )}
            {results.runs.map((run) => (
              <tr key={run.timestamp}>
                <td>
                  <Link to={`/automations/${name}/results/${run.timestamp}`} className="link">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : run.timestamp}
                  </Link>
                </td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td className="text-secondary">
                  {run.duration_s != null ? `${run.duration_s.toFixed(1)}s` : '-'}
                </td>
                <td className="text-secondary">
                  {run.cost_usd != null ? `$${run.cost_usd.toFixed(2)}` : '-'}
                </td>
                <td className="run-preview">
                  {run.output_preview || (run.error ? run.error.slice(0, 80) : '-')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  )
}

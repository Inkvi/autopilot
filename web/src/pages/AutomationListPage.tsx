import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import type { AutomationSummary } from '../api/client'
import { triggerRun } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { showToast } from '../components/Toast'

interface Props {
  automations: AutomationSummary[]
  onRefresh: () => void
  onTrigger: (name: string) => void
}

export function AutomationListPage({ automations, onRefresh, onTrigger }: Props) {
  const handleRun = async (name: string) => {
    try {
      await triggerRun(name)
      onTrigger(name)
      showToast('success', `${name} started`)
      onRefresh()
    } catch (err) {
      showToast('error', err instanceof Error ? err.message : 'Failed to trigger run')
    }
  }

  return (
    <div>
      <div className="page-header">
        <h2>Automations</h2>
      </div>
      <div className="card-list">
        {automations.length === 0 && (
          <p className="text-muted">No automations found.</p>
        )}
        {automations.map((a) => (
          <div key={a.name} className="card">
            <Link to={`/automations/${a.name}`} className="card-main">
              <div className="card-title">{a.name}</div>
              <div className="card-subtitle">
                {a.backend} · {a.model || 'default'} · every {a.schedule}
              </div>
            </Link>
            <div className="card-right">
              <div className="card-status">
                <StatusBadge status={a.last_status} isRunning={a.is_running} />
                <span className="text-muted text-sm">
                  {a.last_run
                    ? formatDistanceToNow(new Date(a.last_run), { addSuffix: true })
                    : 'never'}
                </span>
              </div>
              <button
                className="btn btn-secondary"
                onClick={() => handleRun(a.name)}
                disabled={a.is_running}
              >
                {a.is_running ? 'Running' : 'Run'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

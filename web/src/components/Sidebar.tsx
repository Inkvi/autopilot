import { NavLink } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import type { AutomationSummary } from '../api/client'

interface SidebarProps {
  automations: AutomationSummary[]
}

const dotColor = (status: string | null, isRunning: boolean) => {
  if (isRunning) return '#facc15'
  if (status === 'ok') return '#4ade80'
  if (status === 'error') return '#f85149'
  return '#6b7280'
}

export function Sidebar({ automations }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-title">Autopilot</div>
      <NavLink to="/" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`} end>
        All Automations
      </NavLink>
      <div className="sidebar-section-label">Automations</div>
      {automations.map((a) => (
        <NavLink
          key={a.name}
          to={`/automations/${a.name}`}
          className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
        >
          <span
            className="status-dot"
            style={{ background: dotColor(a.last_status, a.is_running) }}
          />
          <span className="sidebar-link-content">
            <span className="sidebar-link-name">{a.name}</span>
            {a.last_run && (
              <span className="sidebar-link-time">
                {formatDistanceToNow(new Date(a.last_run), { addSuffix: true })}
              </span>
            )}
          </span>
        </NavLink>
      ))}
    </aside>
  )
}

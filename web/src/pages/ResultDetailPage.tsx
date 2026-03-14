import { useParams, Link } from 'react-router-dom'
import { fetchResult, fetchConversation } from '../api/client'
import type { ConversationEvent } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { StatusBadge } from '../components/StatusBadge'
import { MarkdownRenderer } from '../components/MarkdownRenderer'
import { ConversationView } from '../components/ConversationView'
import { useCallback, useEffect, useState } from 'react'

export function ResultDetailPage() {
  const { name, ts } = useParams<{ name: string; ts: string }>()
  const [activeTab, setActiveTab] = useState<'output' | 'steps'>('output')
  const [conversation, setConversation] = useState<ConversationEvent[] | null>(null)
  const [loadingConv, setLoadingConv] = useState(false)

  const { data, loading } = usePolling(
    useCallback(() => fetchResult(name!, ts!), [name, ts]),
    0,
  )

  useEffect(() => {
    if (activeTab === 'steps' && conversation === null && !loadingConv) {
      setLoadingConv(true)
      fetchConversation(name!, ts!)
        .then((res) => setConversation(res.events))
        .catch(() => setConversation([]))
        .finally(() => setLoadingConv(false))
    }
  }, [activeTab, conversation, loadingConv, name, ts])

  if (loading || !data) return <div className="text-muted">Loading...</div>

  const { meta, output, has_conversation } = data

  return (
    <div>
      <div className="breadcrumb">
        <Link to={`/automations/${name}`} className="link">← {name}</Link>
        <span className="text-muted"> / {meta.started_at ? new Date(meta.started_at).toLocaleString() : ts}</span>
      </div>

      <div className="meta-cards">
        <div className="meta-card">
          <div className="meta-label">Status</div>
          <StatusBadge status={meta.status} />
        </div>
        <div className="meta-card">
          <div className="meta-label">Duration</div>
          <div className="meta-value">
            {meta.duration_s != null ? `${meta.duration_s.toFixed(1)}s` : '-'}
          </div>
        </div>
        <div className="meta-card">
          <div className="meta-label">Cost</div>
          <div className="meta-value">
            {meta.cost_usd != null ? `$${meta.cost_usd.toFixed(2)}` : '-'}
          </div>
        </div>
        <div className="meta-card">
          <div className="meta-label">Tokens</div>
          <div className="meta-value">
            {meta.tokens_in != null ? `${meta.tokens_in.toLocaleString()} in` : '-'}
            {meta.tokens_out != null ? ` / ${meta.tokens_out.toLocaleString()} out` : ''}
          </div>
        </div>
      </div>

      {meta.error && (
        <div className="error-box">
          <strong>Error:</strong> {meta.error}
        </div>
      )}

      <div className="tab-bar">
        <button
          className={`tab-btn ${activeTab === 'output' ? 'tab-active' : ''}`}
          onClick={() => setActiveTab('output')}
        >
          Output
        </button>
        {has_conversation && (
          <button
            className={`tab-btn ${activeTab === 'steps' ? 'tab-active' : ''}`}
            onClick={() => setActiveTab('steps')}
          >
            Steps
          </button>
        )}
      </div>

      {activeTab === 'output' && (
        <div className="output-container">
          <MarkdownRenderer content={output} />
        </div>
      )}

      {activeTab === 'steps' && (
        <div className="output-container">
          {loadingConv && <div className="text-muted">Loading conversation...</div>}
          {!loadingConv && conversation && <ConversationView events={conversation} />}
        </div>
      )}
    </div>
  )
}

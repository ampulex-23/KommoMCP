import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSessions } from '../api'
import { RefreshCw, Search } from 'lucide-react'

export default function Sessions() {
  const [sessions, setSessions] = useState([])
  const [filtered, setFiltered] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    applyFilters()
  }, [sessions, search, statusFilter])

  async function loadData() {
    setLoading(true)
    try {
      const data = await getSessions(300)
      setSessions(data.sessions || [])
    } catch (e) {
      console.error('Failed to load sessions:', e)
    } finally {
      setLoading(false)
    }
  }

  function applyFilters() {
    let result = sessions
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(s =>
        String(s.user_id).toLowerCase().includes(q) ||
        (s.user_message || '').toLowerCase().includes(q) ||
        (s.session_id || '').toLowerCase().includes(q)
      )
    }
    if (statusFilter === 'error') {
      result = result.filter(s => s.errors > 0)
    } else if (statusFilter === 'success') {
      result = result.filter(s => !s.errors)
    }
    setFiltered(result)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Sessions</h1>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-brand hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by user, message, session ID..."
            className="w-full pl-9 pr-3 py-2 bg-surface border border-surface-3 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 bg-surface border border-surface-3 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand"
        >
          <option value="">All statuses</option>
          <option value="success">Success</option>
          <option value="error">With errors</option>
        </select>
        <span className="text-xs text-slate-500">{filtered.length} sessions</span>
      </div>

      {/* Sessions list */}
      <div className="space-y-2">
        {loading && !sessions.length ? (
          <div className="text-slate-400 text-center py-12">Loading sessions...</div>
        ) : filtered.length === 0 ? (
          <div className="text-slate-400 text-center py-12">No sessions found</div>
        ) : (
          filtered.map(s => {
            const time = s.started_at ? new Date(s.started_at).toLocaleString() : ''
            const dur = (s.duration_ms || 0).toFixed(0)
            return (
              <div
                key={s.session_id}
                onClick={() => navigate(`/session/${s.session_id}`)}
                className="bg-surface-2 rounded-xl border border-surface-3 p-4 flex flex-wrap items-center gap-4 cursor-pointer hover:border-brand/50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono text-brand">{s.session_id.substring(0, 24)}</span>
                    {s.errors > 0 ? (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-red-500/20 text-red-400">
                        {s.errors} error{s.errors > 1 ? 's' : ''}
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400">OK</span>
                    )}
                  </div>
                  <p className="text-sm text-slate-300 truncate">{s.user_message || '—'}</p>
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-500">
                  <span>👤 {s.user_id}</span>
                  <span>⏱️ {dur}ms</span>
                  <span>🔄 {s.iterations || 0}</span>
                  <span>📡 {s.api_calls || 0}</span>
                  <span className="text-slate-600">{time}</span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

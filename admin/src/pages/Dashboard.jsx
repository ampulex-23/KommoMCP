import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSessions, getUsers } from '../api'
import { Activity, Users, AlertTriangle, Clock, Wrench, BarChart3 } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'

const COLORS = ['#6366f1', '#818cf8', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316']

function StatCard({ icon: Icon, label, value, color = 'text-brand' }) {
  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-slate-400 uppercase">{label}</span>
        <Icon size={18} className="text-slate-500" />
      </div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [sessions, setSessions] = useState([])
  const [users, setUsers] = useState(null)
  const [timelineData, setTimelineData] = useState([])
  const [toolData, setToolData] = useState([])
  const navigate = useNavigate()

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    try {
      const [sessData, usersData] = await Promise.all([
        getSessions(200),
        getUsers().catch(() => null),
      ])
      setStats(sessData.stats)
      setSessions(sessData.sessions || [])
      setUsers(usersData)
      buildCharts(sessData.sessions || [])
    } catch (e) {
      console.error('Failed to load dashboard data:', e)
    }
  }

  function buildCharts(sessions) {
    // Timeline
    const byDate = {}
    const errByDate = {}
    sessions.forEach(s => {
      const d = (s.started_at || '').substring(0, 10)
      if (!d) return
      byDate[d] = (byDate[d] || 0) + 1
      if (s.errors) errByDate[d] = (errByDate[d] || 0) + 1
    })
    const labels = Object.keys(byDate).sort()
    setTimelineData(labels.map(d => ({
      date: d.substring(5),
      sessions: byDate[d],
      errors: errByDate[d] || 0,
    })))

    // Tool usage from session summaries
    const toolCounts = {}
    sessions.forEach(s => {
      const uid = String(s.user_id || '')
      toolCounts[uid] = (toolCounts[uid] || 0) + (s.iterations || 0)
    })
    const sorted = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 8)
    setToolData(sorted.map(([name, value]) => ({ name: name.substring(0, 20), value })))
  }

  if (!stats) {
    return <div className="text-slate-400 text-center py-12">Loading dashboard...</div>
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Dashboard</h1>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard icon={BarChart3} label="Total Sessions" value={stats.total || 0} />
        <StatCard icon={Activity} label="Today" value={stats.today || 0} color="text-blue-400" />
        <StatCard icon={AlertTriangle} label="Errors" value={stats.with_errors || 0} color="text-red-400" />
        <StatCard icon={Clock} label="Avg Duration" value={`${(stats.avg_duration || 0).toFixed(0)}ms`} color="text-amber-400" />
        <StatCard icon={Users} label="Unique Users" value={stats.unique_users || 0} color="text-green-400" />
        <StatCard icon={Wrench} label="Total Tools" value={stats.total_tools || 0} color="text-brand-light" />
      </div>

      {/* Users summary */}
      {users && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase mb-3">Connected Users</h3>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-white">{users.total_users || 0}</div>
              <div className="text-xs text-slate-500">TG Users</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-white">{users.total_tenants || 0}</div>
              <div className="text-xs text-slate-500">CRM Connections</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-green-400">{users.active_tenants || 0}</div>
              <div className="text-xs text-slate-500">Active CRMs</div>
            </div>
          </div>
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase mb-3">Sessions Over Time</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={timelineData}>
              <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} />
              <YAxis tick={{ fill: '#64748b' }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
              />
              <Bar dataKey="sessions" fill="#6366f1" radius={[4, 4, 0, 0]} />
              <Bar dataKey="errors" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-surface-2 rounded-xl border border-surface-3 p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase mb-3">Activity by User</h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={toolData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
                {toolData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent sessions */}
      <div className="bg-surface-2 rounded-xl border border-surface-3 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-400 uppercase">Recent Sessions</h3>
          <button
            onClick={() => navigate('/sessions')}
            className="text-xs text-brand hover:text-brand-light transition-colors"
          >
            View all →
          </button>
        </div>
        <div className="space-y-2">
          {sessions.slice(0, 5).map(s => (
            <div
              key={s.session_id}
              onClick={() => navigate(`/session/${s.session_id}`)}
              className="flex items-center gap-4 p-3 rounded-lg hover:bg-surface-3/50 cursor-pointer transition-colors"
            >
              <div className="flex-1 min-w-0">
                <p className="text-sm text-slate-300 truncate">{s.user_message || '—'}</p>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>👤 {s.user_id}</span>
                <span>🔄 {s.iterations || 0}</span>
                {s.errors > 0 && <span className="text-red-400">❌ {s.errors}</span>}
                <span>{s.started_at ? new Date(s.started_at).toLocaleTimeString() : ''}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

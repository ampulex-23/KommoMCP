import { useState, useEffect } from 'react'
import { getUsers } from '../api'
import { User, Database, CheckCircle, Clock, AlertCircle } from 'lucide-react'

function StatusBadge({ status }) {
  const map = {
    active: { color: 'bg-green-500/20 text-green-400', label: 'Active' },
    pending: { color: 'bg-amber-500/20 text-amber-400', label: 'Pending' },
    provisioning: { color: 'bg-blue-500/20 text-blue-400', label: 'Provisioning' },
    error: { color: 'bg-red-500/20 text-red-400', label: 'Error' },
  }
  const s = map[status] || { color: 'bg-slate-500/20 text-slate-400', label: status || '?' }
  return (
    <span className={`px-2 py-0.5 text-xs rounded-full ${s.color}`}>{s.label}</span>
  )
}

export default function Users() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getUsers()
      .then(setData)
      .catch(e => console.error('Failed to load users:', e))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="text-slate-400 text-center py-12">Loading users...</div>
  }

  if (!data || !data.users) {
    return <div className="text-slate-400 text-center py-12">No user data available</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Users & CRM</h1>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <span>{data.total_users} users</span>
          <span>{data.total_tenants} CRMs</span>
          <span className="text-green-400">{data.active_tenants} active</span>
        </div>
      </div>

      <div className="space-y-4">
        {data.users.map(user => (
          <div key={user.telegram_user_id} className="bg-surface-2 rounded-xl border border-surface-3 overflow-hidden">
            {/* User header */}
            <div className="p-4 border-b border-surface-3 flex items-center gap-4">
              <div className="w-10 h-10 rounded-full bg-brand/20 flex items-center justify-center">
                <User size={20} className="text-brand-light" />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-white font-semibold">
                    {user.telegram_username ? `@${user.telegram_username}` : `User ${user.telegram_user_id}`}
                  </span>
                  <span className="text-xs text-slate-500">ID: {user.telegram_user_id}</span>
                </div>
                <div className="text-xs text-slate-500">
                  {user.tenants.length} CRM connection{user.tenants.length !== 1 ? 's' : ''}
                  {user.active_tenant_id && (
                    <span className="ml-2 text-brand-light">
                      Active: {user.tenants.find(t => t.id === user.active_tenant_id)?.label || '—'}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Tenants */}
            <div className="divide-y divide-surface-3">
              {user.tenants.map(tenant => (
                <div
                  key={tenant.id}
                  className={`p-4 flex items-center gap-4 ${
                    tenant.id === user.active_tenant_id ? 'bg-brand/5' : ''
                  }`}
                >
                  <Database size={16} className="text-slate-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-white font-medium">
                        {tenant.label || tenant.kommo_domain || 'Unnamed'}
                      </span>
                      <StatusBadge status={tenant.status} />
                      {tenant.id === user.active_tenant_id && (
                        <span className="text-xs text-brand-light">◀ active</span>
                      )}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-slate-500 mt-1">
                      {tenant.kommo_domain && <span>🌐 {tenant.kommo_domain}</span>}
                      <span>
                        {tenant.has_kommo ? <CheckCircle size={12} className="inline text-green-400" /> : <AlertCircle size={12} className="inline text-red-400" />}
                        {' '}Kommo
                      </span>
                      <span>
                        {tenant.has_openai ? <CheckCircle size={12} className="inline text-green-400" /> : <AlertCircle size={12} className="inline text-red-400" />}
                        {' '}OpenAI
                      </span>
                      {tenant.created_at && (
                        <span>
                          <Clock size={12} className="inline" /> {new Date(tenant.created_at).toLocaleDateString()}
                        </span>
                      )}
                      {tenant.requests_today > 0 && (
                        <span>📡 {tenant.requests_today}/{tenant.requests_limit} req</span>
                      )}
                    </div>
                  </div>
                  <div className="text-xs text-slate-600 font-mono truncate max-w-[120px]" title={tenant.id}>
                    {tenant.id.substring(0, 8)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

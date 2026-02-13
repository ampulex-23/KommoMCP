import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getSession } from '../api'
import { ArrowLeft, CheckCircle, XCircle, ChevronDown, ChevronRight } from 'lucide-react'

function esc(t) {
  if (!t) return ''
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function ToolCall({ call }) {
  const [open, setOpen] = useState(false)
  const isErr = !call.success || JSON.stringify(call.result || {}).includes('"error"')
  const resultStr = JSON.stringify(call.result || {}, null, 2)

  return (
    <div className={`border-l-2 ${isErr ? 'border-red-500' : 'border-green-500'} pl-3 py-1`}>
      <div className="flex items-center gap-2">
        {isErr ? <XCircle size={14} className="text-red-400" /> : <CheckCircle size={14} className="text-green-400" />}
        <span className={`text-sm font-semibold ${isErr ? 'text-red-400' : 'text-amber-300'}`}>
          {call.tool_name || '?'}
        </span>
      </div>
      <div className="text-xs text-slate-500 font-mono mt-1 break-all">
        {JSON.stringify(call.arguments || {})}
      </div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mt-1 transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Result ({resultStr.length} chars)
      </button>
      {open && (
        <pre className={`text-xs ${isErr ? 'text-red-400' : 'text-green-400'} font-mono mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all bg-surface rounded p-2`}>
          {resultStr.substring(0, 3000)}
        </pre>
      )}
    </div>
  )
}

export default function SessionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showPrompt, setShowPrompt] = useState(false)

  useEffect(() => {
    getSession(id)
      .then(setSession)
      .catch(e => console.error('Failed to load session:', e))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return <div className="text-slate-400 text-center py-12">Loading session...</div>
  }

  if (!session) {
    return <div className="text-slate-400 text-center py-12">Session not found</div>
  }

  const dur = (session.duration_ms || 0).toFixed(0)
  const hasErrors = session.errors && session.errors.length > 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate(-1)}
          className="p-2 rounded-lg hover:bg-surface-3/50 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-white font-mono">{id.substring(0, 30)}</h1>
            {hasErrors ? (
              <span className="px-2 py-0.5 text-xs rounded-full bg-red-500/20 text-red-400">
                {session.errors.length} error{session.errors.length > 1 ? 's' : ''}
              </span>
            ) : (
              <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400">OK</span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-500 mt-1">
            <span>👤 {session.user_id}</span>
            <span>⏱️ {dur}ms</span>
            <span>🔄 {(session.iterations || []).length} iterations</span>
            <span>📡 {(session.api_calls || []).length} API calls</span>
            <span>{session.started_at ? new Date(session.started_at).toLocaleString() : ''}</span>
          </div>
        </div>
      </div>

      {/* User message */}
      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
        <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">📝 User Message</h3>
        <div className="bg-surface rounded-lg p-3 text-sm font-mono text-slate-300 whitespace-pre-wrap">
          {session.user_message || '—'}
        </div>
      </div>

      {/* Iterations */}
      {session.iterations && session.iterations.length > 0 && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-3">
            🔄 Iterations ({session.iterations.length})
          </h3>
          <div className="space-y-3">
            {session.iterations.map((it, i) => (
              <div key={i} className="bg-surface rounded-lg p-3">
                <div className="flex justify-between text-xs text-slate-500 mb-2">
                  <span>Iteration {it.iteration || i + 1}</span>
                  <span>{(it.tool_calls || []).length} tool calls</span>
                </div>
                <div className="space-y-2">
                  {(it.tool_calls || []).map((tc, j) => (
                    <ToolCall key={j} call={tc} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Errors */}
      {hasErrors && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
          <h3 className="text-xs font-semibold text-red-400 uppercase mb-2">
            ❌ Errors ({session.errors.length})
          </h3>
          <div className="space-y-2">
            {session.errors.map((e, i) => (
              <div key={i} className="bg-red-500/10 rounded-lg p-3 text-sm">
                <span className="font-semibold text-red-400">{e.type || 'error'}</span>
                <span className="text-red-300 ml-2">{e.message || ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Response */}
      {session.final_response && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">💬 Response</h3>
          <div className="bg-green-500/5 border border-green-500/20 rounded-lg p-3 text-sm text-slate-300 whitespace-pre-wrap">
            {session.final_response}
          </div>
        </div>
      )}

      {/* Dynamic prompt */}
      {session.dynamic_prompt && (
        <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
          <button
            onClick={() => setShowPrompt(!showPrompt)}
            className="flex items-center gap-2 text-xs font-semibold text-slate-500 uppercase hover:text-slate-300 transition-colors"
          >
            {showPrompt ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            📋 Dynamic Prompt ({session.dynamic_prompt.length} chars)
          </button>
          {showPrompt && (
            <div className="bg-surface rounded-lg p-3 mt-2 text-xs font-mono text-slate-400 max-h-64 overflow-auto whitespace-pre-wrap">
              {session.dynamic_prompt.substring(0, 5000)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import { useState } from 'react'
import { login } from '../api'

export default function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await login(email, password)
      if (data.error) {
        setError(data.error)
      } else {
        onLogin(data)
      }
    } catch {
      setError('Connection error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full bg-surface flex items-center justify-center">
      <div className="w-full max-w-md p-8">
        <div className="bg-surface-2 rounded-2xl shadow-2xl p-8 border border-surface-3">
          <div className="text-center mb-8">
            <div className="text-4xl mb-2">🔍</div>
            <h1 className="text-2xl font-bold text-white">KommoMCP Admin</h1>
            <p className="text-slate-400 text-sm mt-1">Sign in to access the dashboard</p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-4 py-3 bg-surface border border-surface-3 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full px-4 py-3 bg-surface border border-surface-3 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent"
                placeholder="••••••••"
              />
            </div>
            {error && (
              <p className="text-red-400 text-sm text-center">{error}</p>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-brand hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold rounded-lg transition-colors"
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

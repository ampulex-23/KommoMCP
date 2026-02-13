import { Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { checkAuth } from './api'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Users from './pages/Users'
import Sessions from './pages/Sessions'
import SessionDetail from './pages/SessionDetail'

function App() {
  const [user, setUser] = useState(undefined) // undefined = loading

  useEffect(() => {
    checkAuth().then(u => setUser(u || null))
  }, [])

  if (user === undefined) {
    return (
      <div className="h-full bg-surface flex items-center justify-center">
        <div className="text-slate-400 text-lg">Loading...</div>
      </div>
    )
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login onLogin={setUser} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <Layout user={user}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/users" element={<Users />} />
        <Route path="/sessions" element={<Sessions />} />
        <Route path="/session/:id" element={<SessionDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default App

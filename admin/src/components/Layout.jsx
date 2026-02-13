import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Users, Activity, LogOut } from 'lucide-react'
import { logout } from '../api'

const nav = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/users', icon: Users, label: 'Users & CRM' },
  { to: '/sessions', icon: Activity, label: 'Sessions' },
]

export default function Layout({ user, children }) {
  return (
    <div className="h-full flex bg-surface">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-surface-2 border-r border-surface-3 flex flex-col">
        <div className="p-4 border-b border-surface-3">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔍</span>
            <span className="text-white font-bold text-sm">KommoMCP Admin</span>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand/20 text-brand-light'
                    : 'text-slate-400 hover:text-white hover:bg-surface-3/50'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-surface-3">
          <div className="text-xs text-slate-500 mb-2 px-3 truncate">{user?.email}</div>
          <button
            onClick={logout}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-red-400 hover:bg-surface-3/50 transition-colors w-full"
          >
            <LogOut size={16} />
            Logout
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto p-6">
        {children}
      </main>
    </div>
  )
}

"""
Monitoring dashboard for KommoMCP - beautiful web UI with auth.
Uses Tailwind CSS + Chart.js via CDN.
"""

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime
from typing import Dict, Optional

from aiohttp import web

from kommo_mcp.telegram.interaction_logger import get_interaction_logger

logger = logging.getLogger(__name__)

# Auth config
AUTH_USERS = {
    'frwalkr@gmail.com': hashlib.sha256('admin123'.encode()).hexdigest(),
}
# Active sessions: token -> {email, expires}
_auth_sessions: Dict[str, dict] = {}
SESSION_TTL = 86400 * 7  # 7 days
URL_PREFIX = '/logs'  # nginx proxy prefix


def _check_auth(request) -> Optional[str]:
    """Check if request is authenticated. Returns email or None."""
    token = request.cookies.get('session_token')
    if not token:
        return None
    session = _auth_sessions.get(token)
    if not session:
        return None
    if time.time() > session['expires']:
        del _auth_sessions[token]
        return None
    return session['email']


# ─── Login page ───

LOGIN_HTML = '''<!DOCTYPE html>
<html lang="ru" class="h-full">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KommoMCP - Login</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={theme:{extend:{colors:{brand:'#6366f1',surface:'#0f172a','surface-2':'#1e293b','surface-3':'#334155'}}}}</script>
<style>body{font-family:Inter,system-ui,sans-serif}</style>
</head>
<body class="h-full bg-surface flex items-center justify-center">
<div class="w-full max-w-md p-8">
  <div class="bg-surface-2 rounded-2xl shadow-2xl p-8 border border-surface-3">
    <div class="text-center mb-8">
      <div class="text-4xl mb-2">🔍</div>
      <h1 class="text-2xl font-bold text-white">KommoMCP Monitor</h1>
      <p class="text-slate-400 text-sm mt-1">Sign in to access the dashboard</p>
    </div>
    <form method="POST" action="%%PREFIX%%/api/login" class="space-y-4">
      <div>
        <label class="block text-sm font-medium text-slate-300 mb-1">Email</label>
        <input type="email" name="email" required
          class="w-full px-4 py-3 bg-surface border border-surface-3 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent"
          placeholder="you@example.com">
      </div>
      <div>
        <label class="block text-sm font-medium text-slate-300 mb-1">Password</label>
        <input type="password" name="password" required
          class="w-full px-4 py-3 bg-surface border border-surface-3 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent"
          placeholder="••••••••">
      </div>
      %%ERROR%%
      <button type="submit"
        class="w-full py-3 bg-brand hover:bg-indigo-500 text-white font-semibold rounded-lg transition-colors">
        Sign In
      </button>
    </form>
  </div>
</div>
</body>
</html>'''


# ─── Dashboard page ───

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KommoMCP Monitor</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>tailwind.config={theme:{extend:{colors:{brand:'#6366f1','brand-light':'#818cf8',surface:'#0f172a','surface-2':'#1e293b','surface-3':'#334155',success:'#22c55e',danger:'#ef4444',warning:'#f59e0b',info:'#3b82f6'}}}}</script>
<style>
body{font-family:Inter,system-ui,sans-serif}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:#1e293b}
::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
.fade-in{animation:fadeIn .3s ease-in}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
</style>
</head>
<body class="bg-surface text-slate-200 min-h-screen">

<!-- Navbar -->
<nav class="bg-surface-2 border-b border-surface-3 sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="flex items-center justify-between h-16">
      <div class="flex items-center gap-3">
        <span class="text-2xl">🔍</span>
        <h1 class="text-lg font-bold text-white">KommoMCP Monitor</h1>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-sm text-slate-400">%%EMAIL%%</span>
        <a href="%%PREFIX%%/api/logout" class="text-sm text-slate-400 hover:text-white transition-colors">Logout</a>
      </div>
    </div>
  </div>
</nav>

<main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">

  <!-- Stats cards -->
  <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6" id="statsGrid"></div>

  <!-- Charts row -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
    <div class="bg-surface-2 rounded-xl border border-surface-3 p-5">
      <h3 class="text-sm font-semibold text-slate-400 uppercase mb-3">Sessions Over Time</h3>
      <div style="position:relative;height:220px"><canvas id="timelineChart"></canvas></div>
    </div>
    <div class="bg-surface-2 rounded-xl border border-surface-3 p-5">
      <h3 class="text-sm font-semibold text-slate-400 uppercase mb-3">Tool Usage</h3>
      <div style="position:relative;height:220px"><canvas id="toolsChart"></canvas></div>
    </div>
  </div>

  <!-- Filters -->
  <div class="bg-surface-2 rounded-xl border border-surface-3 p-4 mb-4 flex flex-wrap items-center gap-3">
    <button onclick="loadData()" class="px-4 py-2 bg-brand hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
      Refresh
    </button>
    <input type="text" id="filterUser" placeholder="Filter by user ID..."
      class="px-3 py-2 bg-surface border border-surface-3 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-brand w-48"
      oninput="applyFilters()">
    <select id="filterStatus" onchange="applyFilters()"
      class="px-3 py-2 bg-surface border border-surface-3 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand">
      <option value="">All statuses</option>
      <option value="success">Success</option>
      <option value="error">With errors</option>
    </select>
    <select id="filterTenant" onchange="applyFilters()"
      class="px-3 py-2 bg-surface border border-surface-3 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand">
      <option value="">All tenants</option>
    </select>
    <div class="ml-auto text-xs text-slate-500" id="lastUpdate"></div>
  </div>

  <!-- Sessions list -->
  <div id="sessionsList" class="space-y-3"></div>

</main>

<script>
let allSessions = [];
let timelineChart = null;
let toolsChart = null;

let isAutoRefresh = false;

async function loadData(auto) {
  try {
    const resp = await fetch('%%PREFIX%%/api/sessions?limit=100');
    const data = await resp.json();
    allSessions = data.sessions || [];
    renderStats(data.stats);
    populateTenantFilter();
    // Only re-render session list if no sessions are expanded or manual refresh
    if (!auto || !document.querySelector('.session-details:not(.hidden)')) {
      applyFilters();
    }
    renderCharts();
    document.getElementById('lastUpdate').textContent = 'Updated: ' + new Date().toLocaleTimeString();
  } catch (e) {
    if (!auto) {
      document.getElementById('sessionsList').innerHTML =
        '<div class="text-center text-slate-500 py-12">Failed to load data</div>';
    }
  }
}

function renderStats(s) {
  if (!s) return;
  const cards = [
    {label:'Total Sessions', value:s.total||0, icon:'📊', color:'brand'},
    {label:'Today', value:s.today||0, icon:'📅', color:'info'},
    {label:'Errors', value:s.with_errors||0, icon:'❌', color:'danger'},
    {label:'Avg Duration', value:(s.avg_duration||0).toFixed(0)+'ms', icon:'⏱️', color:'warning'},
    {label:'Unique Users', value:s.unique_users||0, icon:'👤', color:'success'},
    {label:'Total Tools', value:s.total_tools||0, icon:'🔧', color:'brand-light'},
  ];
  document.getElementById('statsGrid').innerHTML = cards.map(c => `
    <div class="bg-surface-2 rounded-xl border border-surface-3 p-4 fade-in">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-medium text-slate-400 uppercase">${c.label}</span>
        <span class="text-lg">${c.icon}</span>
      </div>
      <div class="text-2xl font-bold text-${c.color}">${c.value}</div>
    </div>
  `).join('');
}

function populateTenantFilter() {
  const users = [...new Set(allSessions.map(s => String(s.user_id)))];
  const sel = document.getElementById('filterTenant');
  const current = sel.value;
  sel.innerHTML = '<option value="">All tenants</option>' +
    users.map(u => `<option value="${u}"${u===current?' selected':''}>${u}</option>`).join('');
}

function applyFilters() {
  const userFilter = document.getElementById('filterUser').value.toLowerCase();
  const statusFilter = document.getElementById('filterStatus').value;
  const tenantFilter = document.getElementById('filterTenant').value;
  const filtered = allSessions.filter(s => {
    if (userFilter && !String(s.user_id).toLowerCase().includes(userFilter) &&
        !(s.user_message||'').toLowerCase().includes(userFilter)) return false;
    if (statusFilter === 'error' && !s.errors) return false;
    if (statusFilter === 'success' && s.errors) return false;
    if (tenantFilter && String(s.user_id) !== tenantFilter) return false;
    return true;
  });
  renderSessions(filtered);
}

function renderSessions(sessions) {
  if (!sessions.length) {
    document.getElementById('sessionsList').innerHTML =
      '<div class="text-center text-slate-500 py-12">No sessions found</div>';
    return;
  }
  document.getElementById('sessionsList').innerHTML = sessions.map(s => {
    const time = s.started_at ? new Date(s.started_at).toLocaleString() : '';
    const dur = (s.duration_ms||0).toFixed(0);
    const statusBadge = s.errors
      ? `<span class="px-2 py-0.5 text-xs rounded-full bg-red-500/20 text-red-400">${s.errors} errors</span>`
      : '<span class="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400">OK</span>';
    return `
    <div class="bg-surface-2 rounded-xl border border-surface-3 overflow-hidden hover:border-brand/50 transition-colors fade-in" data-sid="${s.session_id}">
      <div class="p-4 flex flex-wrap items-center gap-4 cursor-pointer" onclick="toggleSession(this.parentElement.parentElement, '${s.session_id}')">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-mono text-brand">${s.session_id.substring(0,20)}</span>
            ${statusBadge}
          </div>
          <p class="text-sm text-slate-300 truncate">${esc(s.user_message||'')}</p>
        </div>
        <div class="flex items-center gap-4 text-xs text-slate-400">
          <span title="User ID">👤 ${s.user_id}</span>
          <span title="Duration">⏱️ ${dur}ms</span>
          <span title="Iterations">🔄 ${s.iterations||0}</span>
          <span title="API calls">📡 ${s.api_calls||0}</span>
          <span class="text-slate-500">${time}</span>
        </div>
      </div>
      <div class="session-details hidden border-t border-surface-3"></div>
    </div>`;
  }).join('');
}

async function toggleSession(el, sid) {
  if (event) event.stopPropagation();
  const details = el.querySelector('.session-details');
  if (!details.classList.contains('hidden')) {
    details.classList.add('hidden');
    return;
  }
  details.classList.remove('hidden');
  if (details.dataset.loaded) return;
  details.innerHTML = '<div class="p-4 text-slate-400 text-sm">Loading...</div>';
  try {
    const resp = await fetch('%%PREFIX%%/api/session/' + sid);
    const s = await resp.json();
    details.innerHTML = renderDetails(s);
    details.dataset.loaded = '1';
  } catch(e) {
    details.innerHTML = '<div class="p-4 text-red-400 text-sm">Failed to load</div>';
  }
}

function renderDetails(s) {
  let h = '';

  // User message
  h += `<div class="p-4 border-b border-surface-3">
    <h4 class="text-xs font-semibold text-slate-400 uppercase mb-2">📝 User Message</h4>
    <div class="bg-surface rounded-lg p-3 text-sm font-mono text-slate-300 whitespace-pre-wrap">${esc(s.user_message||'')}</div>
  </div>`;

  // Iterations
  if (s.iterations && s.iterations.length) {
    h += '<div class="p-4 border-b border-surface-3">';
    h += `<h4 class="text-xs font-semibold text-slate-400 uppercase mb-3">🔄 Iterations (${s.iterations.length})</h4>`;
    s.iterations.forEach((it,i) => {
      h += `<div class="bg-surface rounded-lg p-3 mb-2">
        <div class="flex justify-between text-xs text-slate-500 mb-2">
          <span>Iteration ${it.iteration||i+1}</span>
          <span>${(it.tool_calls||[]).length} tool calls</span>
        </div>`;
      (it.tool_calls||[]).forEach(tc => {
        const res = JSON.stringify(tc.result||{}, null, 2);
        const isErr = !tc.success || res.includes('"error"');
        h += `<div class="mt-2 border-l-2 ${isErr?'border-red-500':'border-green-500'} pl-3">
          <div class="text-sm font-semibold ${isErr?'text-red-400':'text-amber-300'}">${tc.tool_name||'?'}</div>
          <div class="text-xs text-slate-500 font-mono mt-1 break-all">${esc(JSON.stringify(tc.arguments||{}))}</div>
          <details class="mt-1" onclick="event.stopPropagation()"><summary class="text-xs text-slate-500 cursor-pointer hover:text-slate-300">Result</summary>
            <pre class="text-xs ${isErr?'text-red-400':'text-green-400'} font-mono mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all">${esc(res.substring(0,1000))}</pre>
          </details>
        </div>`;
      });
      h += '</div>';
    });
    h += '</div>';
  }

  // Errors
  if (s.errors && s.errors.length) {
    h += '<div class="p-4 border-b border-surface-3">';
    h += `<h4 class="text-xs font-semibold text-red-400 uppercase mb-2">❌ Errors (${s.errors.length})</h4>`;
    s.errors.forEach(e => {
      h += `<div class="bg-red-500/10 rounded-lg p-3 mb-2 text-sm">
        <span class="font-semibold text-red-400">${e.type||'error'}</span>
        <span class="text-red-300 ml-2">${esc(e.message||'')}</span>
      </div>`;
    });
    h += '</div>';
  }

  // Response
  if (s.final_response) {
    h += `<div class="p-4 border-b border-surface-3">
      <h4 class="text-xs font-semibold text-slate-400 uppercase mb-2">💬 Response</h4>
      <div class="bg-green-500/5 border border-green-500/20 rounded-lg p-3 text-sm text-slate-300 whitespace-pre-wrap">${esc(s.final_response)}</div>
    </div>`;
  }

  // Dynamic prompt
  if (s.dynamic_prompt) {
    h += `<div class="p-4">
      <details onclick="event.stopPropagation()"><summary class="text-xs font-semibold text-slate-500 uppercase cursor-pointer hover:text-slate-300">📋 Dynamic Prompt (${s.dynamic_prompt.length} chars)</summary>
        <div class="bg-surface rounded-lg p-3 mt-2 text-xs font-mono text-slate-400 max-h-48 overflow-auto whitespace-pre-wrap">${esc(s.dynamic_prompt.substring(0,3000))}</div>
      </details>
    </div>`;
  }

  return h;
}

function renderCharts() {
  renderTimelineChart();
  renderToolsChart();
}

function renderTimelineChart() {
  const byDate = {};
  const errByDate = {};
  allSessions.forEach(s => {
    const d = (s.started_at||'').substring(0,10);
    if (!d) return;
    byDate[d] = (byDate[d]||0) + 1;
    if (s.errors) errByDate[d] = (errByDate[d]||0) + 1;
  });
  const labels = Object.keys(byDate).sort();
  const data = labels.map(l => byDate[l]);
  const errData = labels.map(l => errByDate[l]||0);

  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(document.getElementById('timelineChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {label:'Sessions', data, backgroundColor:'rgba(99,102,241,0.6)', borderRadius:4},
        {label:'Errors', data:errData, backgroundColor:'rgba(239,68,68,0.6)', borderRadius:4},
      ]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{labels:{color:'#94a3b8',font:{size:11}}}},
      scales:{
        x:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1e293b'}},
        y:{ticks:{color:'#64748b'},grid:{color:'#1e293b'},beginAtZero:true}
      }
    }
  });
}

function renderToolsChart() {
  const toolCounts = {};
  allSessions.forEach(s => {
    // We only have summary data here, need detail for tool breakdown
    // Use iterations count as proxy
  });

  // Fetch a few recent sessions for tool data
  Promise.all(
    allSessions.slice(0,20).map(s =>
      fetch('%%PREFIX%%/api/session/'+s.session_id).then(r=>r.json()).catch(()=>null)
    )
  ).then(details => {
    const tc = {};
    details.filter(Boolean).forEach(d => {
      (d.iterations||[]).forEach(it => {
        (it.tool_calls||[]).forEach(c => {
          const name = c.tool_name||'?';
          tc[name] = (tc[name]||0) + 1;
        });
      });
    });
    const sorted = Object.entries(tc).sort((a,b)=>b[1]-a[1]).slice(0,10);
    const labels = sorted.map(x=>x[0]);
    const data = sorted.map(x=>x[1]);
    const colors = ['#6366f1','#818cf8','#3b82f6','#22c55e','#f59e0b','#ef4444','#ec4899','#8b5cf6','#14b8a6','#f97316'];

    if (toolsChart) toolsChart.destroy();
    toolsChart = new Chart(document.getElementById('toolsChart'), {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{data, backgroundColor:colors.slice(0,data.length), borderWidth:0}]
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:11},padding:8}}}
      }
    });
  });
}

function esc(t) {
  if (!t) return '';
  return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Auto-refresh every 30s
loadData(false);
setInterval(() => loadData(true), 30000);
</script>
</body>
</html>'''


# ─── Handlers ───

async def login_page(request):
    """Show login form."""
    if _check_auth(request):
        raise web.HTTPFound(URL_PREFIX + '/')
    html = LOGIN_HTML.replace('%%ERROR%%', '').replace('%%PREFIX%%', URL_PREFIX)
    return web.Response(text=html, content_type='text/html')


async def login_handler(request):
    """Handle login POST."""
    data = await request.post()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    if email in AUTH_USERS and AUTH_USERS[email] == pw_hash:
        token = secrets.token_urlsafe(32)
        _auth_sessions[token] = {'email': email, 'expires': time.time() + SESSION_TTL}
        resp = web.HTTPFound(URL_PREFIX + '/')
        resp.set_cookie('session_token', token, max_age=SESSION_TTL, httponly=True, samesite='Lax', path='/')
        return resp

    html = LOGIN_HTML.replace('%%ERROR%%',
        '<p class="text-red-400 text-sm text-center">Invalid email or password</p>').replace('%%PREFIX%%', URL_PREFIX)
    return web.Response(text=html, content_type='text/html')


async def logout_handler(request):
    """Handle logout."""
    token = request.cookies.get('session_token')
    if token and token in _auth_sessions:
        del _auth_sessions[token]
    resp = web.HTTPFound(URL_PREFIX + '/login')
    resp.del_cookie('session_token')
    return resp


async def index_handler(request):
    """Serve dashboard (auth required)."""
    email = _check_auth(request)
    if not email:
        raise web.HTTPFound(URL_PREFIX + '/login')
    html = DASHBOARD_HTML.replace('%%EMAIL%%', email).replace('%%PREFIX%%', URL_PREFIX)
    return web.Response(text=html, content_type='text/html')


async def sessions_handler(request):
    """Get list of recent sessions (auth required)."""
    if not _check_auth(request):
        return web.json_response({'error': 'Unauthorized'}, status=401)

    limit = int(request.query.get('limit', 100))
    ilog = get_interaction_logger()
    sessions = ilog.get_recent_sessions(limit=limit)

    today = datetime.now().strftime('%Y-%m-%d')
    today_sessions = [s for s in sessions if (s.get('started_at') or '').startswith(today)]
    with_errors = [s for s in sessions if s.get('errors', 0) > 0]
    durations = [s.get('duration_ms', 0) for s in sessions if s.get('duration_ms')]
    unique_users = len(set(str(s.get('user_id', '')) for s in sessions))
    total_tools = sum(s.get('iterations', 0) for s in sessions)

    stats = {
        'total': len(sessions),
        'today': len(today_sessions),
        'with_errors': len(with_errors),
        'avg_duration': sum(durations) / len(durations) if durations else 0,
        'unique_users': unique_users,
        'total_tools': total_tools,
    }

    return web.json_response({'sessions': sessions, 'stats': stats})


async def session_detail_handler(request):
    """Get full session details (auth required)."""
    if not _check_auth(request):
        return web.json_response({'error': 'Unauthorized'}, status=401)

    session_id = request.match_info['session_id']
    ilog = get_interaction_logger()
    session = ilog.get_session(session_id)
    if not session:
        return web.json_response({'error': 'Session not found'}, status=404)
    return web.json_response(session)


def create_logs_app():
    """Create aiohttp application for logs server."""
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_get('/login', login_page)
    app.router.add_post('/api/login', login_handler)
    app.router.add_get('/api/logout', logout_handler)
    app.router.add_get('/api/sessions', sessions_handler)
    app.router.add_get('/api/session/{session_id}', session_detail_handler)
    return app


async def run_logs_server(host='0.0.0.0', port=8765):
    """Run the logs server."""
    app = create_logs_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f'Logs server running at http://{host}:{port}')
    return runner


if __name__ == '__main__':
    import asyncio
    asyncio.run(run_logs_server())

"""
Simple HTTP server for viewing interaction logs with web UI.
"""

import json
import os
from datetime import datetime
from aiohttp import web

from kommo_mcp.telegram.interaction_logger import get_interaction_logger

# HTML template for logs viewer
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KommoMCP Logs</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e; color: #eee; padding: 20px;
        }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        .container { max-width: 1400px; margin: 0 auto; }
        .stats { 
            display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .stat-card {
            background: #16213e; padding: 15px 25px; border-radius: 10px;
            border-left: 4px solid #00d4ff;
        }
        .stat-card h3 { color: #888; font-size: 12px; text-transform: uppercase; }
        .stat-card .value { font-size: 28px; font-weight: bold; color: #00d4ff; }
        .sessions-list { margin-top: 20px; }
        .session {
            background: #16213e; border-radius: 10px; margin-bottom: 15px;
            overflow: hidden; cursor: pointer; transition: all 0.2s;
        }
        .session:hover { background: #1f2b47; }
        .session-header {
            padding: 15px 20px; display: flex; justify-content: space-between;
            align-items: center; flex-wrap: wrap; gap: 10px;
        }
        .session-id { font-family: monospace; color: #00d4ff; font-size: 14px; }
        .session-time { color: #888; font-size: 13px; }
        .session-message { 
            color: #ccc; font-size: 14px; max-width: 500px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .session-stats { display: flex; gap: 15px; }
        .session-stat { 
            font-size: 12px; padding: 4px 10px; border-radius: 15px;
            background: #0f3460;
        }
        .session-stat.error { background: #5c1a1a; color: #ff6b6b; }
        .session-stat.success { background: #1a5c3a; color: #6bff9e; }
        .session-details { 
            display: none; padding: 0 20px 20px; border-top: 1px solid #0f3460;
        }
        .session.expanded .session-details { display: block; }
        .detail-section { margin-top: 15px; }
        .detail-section h4 { 
            color: #00d4ff; font-size: 13px; margin-bottom: 8px;
            text-transform: uppercase;
        }
        .iteration {
            background: #0f3460; padding: 12px; border-radius: 8px;
            margin-bottom: 10px;
        }
        .iteration-header { 
            display: flex; justify-content: space-between; margin-bottom: 8px;
            font-size: 12px; color: #888;
        }
        .tool-call {
            background: #1a1a2e; padding: 8px 12px; border-radius: 5px;
            margin-top: 8px; font-size: 13px;
        }
        .tool-name { color: #ffd93d; font-weight: bold; }
        .tool-args { color: #888; font-family: monospace; font-size: 11px; }
        .tool-result { 
            color: #6bff9e; font-family: monospace; font-size: 11px;
            max-height: 100px; overflow: auto; margin-top: 5px;
            white-space: pre-wrap; word-break: break-all;
        }
        .tool-result.error { color: #ff6b6b; }
        .error-item {
            background: #3d1a1a; padding: 10px; border-radius: 5px;
            margin-top: 5px; font-size: 13px;
        }
        .error-type { color: #ff6b6b; font-weight: bold; }
        .prompt-box {
            background: #0f3460; padding: 12px; border-radius: 8px;
            font-family: monospace; font-size: 12px; max-height: 200px;
            overflow: auto; white-space: pre-wrap; word-break: break-word;
        }
        .response-box {
            background: #1a3d1a; padding: 12px; border-radius: 8px;
            font-size: 13px; white-space: pre-wrap;
        }
        .refresh-btn {
            background: #00d4ff; color: #1a1a2e; border: none;
            padding: 10px 20px; border-radius: 5px; cursor: pointer;
            font-weight: bold; margin-bottom: 20px;
        }
        .refresh-btn:hover { background: #00b8e6; }
        .filter-bar {
            display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .filter-bar input, .filter-bar select {
            background: #16213e; border: 1px solid #0f3460; color: #eee;
            padding: 8px 12px; border-radius: 5px;
        }
        .no-sessions { color: #888; text-align: center; padding: 40px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 KommoMCP Interaction Logs</h1>
        
        <div class="stats" id="stats"></div>
        
        <div class="filter-bar">
            <button class="refresh-btn" onclick="loadSessions()">🔄 Refresh</button>
            <input type="text" id="filterUser" placeholder="Filter by user ID..." onkeyup="filterSessions()">
            <select id="filterStatus" onchange="filterSessions()">
                <option value="">All statuses</option>
                <option value="success">Success only</option>
                <option value="error">With errors</option>
            </select>
        </div>
        
        <div class="sessions-list" id="sessions"></div>
    </div>
    
    <script>
        let allSessions = [];
        
        async function loadSessions() {
            try {
                const resp = await fetch('/api/sessions?limit=50');
                const data = await resp.json();
                allSessions = data.sessions || [];
                renderStats(data);
                renderSessions(allSessions);
            } catch (e) {
                document.getElementById('sessions').innerHTML = 
                    '<div class="no-sessions">Error loading sessions</div>';
            }
        }
        
        function renderStats(data) {
            const stats = data.stats || {};
            document.getElementById('stats').innerHTML = `
                <div class="stat-card">
                    <h3>Total Sessions</h3>
                    <div class="value">${stats.total || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>Today</h3>
                    <div class="value">${stats.today || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>With Errors</h3>
                    <div class="value">${stats.with_errors || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>Avg Duration</h3>
                    <div class="value">${(stats.avg_duration || 0).toFixed(0)}ms</div>
                </div>
            `;
        }
        
        function filterSessions() {
            const userFilter = document.getElementById('filterUser').value.toLowerCase();
            const statusFilter = document.getElementById('filterStatus').value;
            
            const filtered = allSessions.filter(s => {
                if (userFilter && !String(s.user_id).includes(userFilter)) return false;
                if (statusFilter === 'error' && !s.errors) return false;
                if (statusFilter === 'success' && s.errors) return false;
                return true;
            });
            renderSessions(filtered);
        }
        
        function renderSessions(sessions) {
            if (!sessions.length) {
                document.getElementById('sessions').innerHTML = 
                    '<div class="no-sessions">No sessions found</div>';
                return;
            }
            
            document.getElementById('sessions').innerHTML = sessions.map(s => `
                <div class="session" onclick="toggleSession(this, '${s.session_id}')">
                    <div class="session-header">
                        <div>
                            <div class="session-id">${s.session_id}</div>
                            <div class="session-time">${s.started_at || ''}</div>
                        </div>
                        <div class="session-message">${escapeHtml(s.user_message || '')}</div>
                        <div class="session-stats">
                            <span class="session-stat">⏱ ${(s.duration_ms || 0).toFixed(0)}ms</span>
                            <span class="session-stat">🔧 ${s.iterations || 0} iter</span>
                            <span class="session-stat">📡 ${s.api_calls || 0} API</span>
                            ${s.errors ? `<span class="session-stat error">❌ ${s.errors} errors</span>` : 
                                        `<span class="session-stat success">✓</span>`}
                        </div>
                    </div>
                    <div class="session-details"></div>
                </div>
            `).join('');
        }
        
        async function toggleSession(el, sessionId) {
            el.classList.toggle('expanded');
            const details = el.querySelector('.session-details');
            
            if (el.classList.contains('expanded') && !details.dataset.loaded) {
                details.innerHTML = 'Loading...';
                try {
                    const resp = await fetch(`/api/session/${sessionId}`);
                    const session = await resp.json();
                    details.innerHTML = renderSessionDetails(session);
                    details.dataset.loaded = 'true';
                } catch (e) {
                    details.innerHTML = 'Error loading details';
                }
            }
        }
        
        function renderSessionDetails(s) {
            let html = '';
            
            // User message
            html += `<div class="detail-section">
                <h4>📝 User Message</h4>
                <div class="prompt-box">${escapeHtml(s.user_message || '')}</div>
            </div>`;
            
            // Iterations
            if (s.iterations && s.iterations.length) {
                html += `<div class="detail-section"><h4>🔄 Iterations (${s.iterations.length})</h4>`;
                s.iterations.forEach((it, i) => {
                    html += `<div class="iteration">
                        <div class="iteration-header">
                            <span>Iteration ${it.iteration || i+1}</span>
                            <span>${it.tool_calls?.length || 0} tool calls</span>
                        </div>`;
                    (it.tool_calls || []).forEach(tc => {
                        const resultStr = JSON.stringify(tc.result || {}, null, 2);
                        const isError = !tc.success || resultStr.includes('error');
                        html += `<div class="tool-call">
                            <div class="tool-name">${tc.tool_name || 'unknown'}</div>
                            <div class="tool-args">${escapeHtml(JSON.stringify(tc.arguments || {}))}</div>
                            <div class="tool-result ${isError ? 'error' : ''}">${escapeHtml(resultStr.substring(0, 500))}</div>
                        </div>`;
                    });
                    html += '</div>';
                });
                html += '</div>';
            }
            
            // Errors
            if (s.errors && s.errors.length) {
                html += `<div class="detail-section"><h4>❌ Errors (${s.errors.length})</h4>`;
                s.errors.forEach(err => {
                    html += `<div class="error-item">
                        <span class="error-type">${err.type || 'error'}</span>: ${escapeHtml(err.message || '')}
                    </div>`;
                });
                html += '</div>';
            }
            
            // Response
            if (s.final_response) {
                html += `<div class="detail-section">
                    <h4>💬 Final Response</h4>
                    <div class="response-box">${escapeHtml(s.final_response)}</div>
                </div>`;
            }
            
            // Dynamic prompt (collapsed)
            if (s.dynamic_prompt) {
                html += `<div class="detail-section">
                    <h4>📋 Dynamic Prompt (${s.dynamic_prompt.length} chars)</h4>
                    <div class="prompt-box">${escapeHtml(s.dynamic_prompt.substring(0, 2000))}...</div>
                </div>`;
            }
            
            return html;
        }
        
        function escapeHtml(text) {
            if (!text) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }
        
        // Load on page load
        loadSessions();
    </script>
</body>
</html>
'''


async def index_handler(request):
    """Serve the main HTML page."""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')


async def sessions_handler(request):
    """Get list of recent sessions."""
    limit = int(request.query.get('limit', 50))
    ilog = get_interaction_logger()
    
    sessions = ilog.get_recent_sessions(limit=limit)
    
    # Calculate stats
    today = datetime.now().strftime('%Y-%m-%d')
    today_sessions = [s for s in sessions if s.get('session_id', '').startswith(today.replace('-', ''))]
    with_errors = [s for s in sessions if s.get('errors', 0) > 0]
    durations = [s.get('duration_ms', 0) for s in sessions if s.get('duration_ms')]
    
    stats = {
        'total': len(sessions),
        'today': len(today_sessions),
        'with_errors': len(with_errors),
        'avg_duration': sum(durations) / len(durations) if durations else 0,
    }
    
    return web.json_response({
        'sessions': sessions,
        'stats': stats,
    })


async def session_detail_handler(request):
    """Get full session details."""
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
    print(f'Logs server running at http://{host}:{port}')
    return runner


if __name__ == '__main__':
    import asyncio
    asyncio.run(run_logs_server())

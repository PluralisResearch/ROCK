"""HTML dashboard for the ROCK Model Gateway trace visualization."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

dashboard_router = APIRouter()

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ROCK Gateway Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; }
  .header { background: #1e293b; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #334155; }
  .header h1 { font-size: 20px; font-weight: 600; color: #f1f5f9; }
  .header-controls { display: flex; gap: 12px; align-items: center; }
  .header-controls select, .header-controls button { background: #334155; color: #e2e8f0; border: 1px solid #475569; padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
  .header-controls button.active { background: #3b82f6; border-color: #3b82f6; }
  .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; }
  .card .label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
  .card .sublabel { font-size: 10px; color: #64748b; margin-top: 4px; }
  .card .value { font-size: 28px; font-weight: 700; color: #f1f5f9; }
  .card .value.success { color: #34d399; }
  .card .value.error { color: #f87171; }
  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
  .chart-box { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; }
  .chart-box h3 { font-size: 14px; color: #94a3b8; margin-bottom: 12px; }
  .chart-box.full { grid-column: 1 / -1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 10px 12px; color: #94a3b8; font-weight: 500; border-bottom: 1px solid #334155; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  td { padding: 10px 12px; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #1e293b; }
  .table-box { background: #1e293b; border-radius: 10px; padding: 20px; border: 1px solid #334155; margin-bottom: 24px; }
  .table-box h3 { font-size: 14px; color: #94a3b8; margin-bottom: 12px; }
  .badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
  .badge-success { background: #064e3b; color: #34d399; }
  .badge-error { background: #7f1d1d; color: #f87171; }
  .mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; color: #94a3b8; }
  .loading { text-align: center; padding: 40px; color: #64748b; }
  .clickable { cursor: pointer; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 3px; }
  .clickable:hover { color: #60a5fa; }

  /* Conversation Modal */
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: flex-start; padding: 40px 20px; overflow-y: auto; }
  .modal-overlay.open { display: flex; }
  .modal { background: #1e293b; border-radius: 12px; border: 1px solid #334155; width: 100%; max-width: 900px; max-height: 85vh; display: flex; flex-direction: column; }
  .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #334155; flex-shrink: 0; }
  .modal-header h2 { font-size: 16px; color: #f1f5f9; }
  .modal-header .meta { font-size: 12px; color: #64748b; }
  .modal-close { background: none; border: none; color: #94a3b8; font-size: 24px; cursor: pointer; padding: 0 4px; }
  .modal-close:hover { color: #f1f5f9; }
  .modal-body { overflow-y: auto; padding: 20px; flex: 1; }
  .conv-turn { margin-bottom: 16px; }
  .conv-turn:last-child { margin-bottom: 0; }
  .conv-bubble { padding: 12px 16px; border-radius: 10px; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto; }
  .conv-role { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; padding-left: 4px; }
  .conv-role.user { color: #60a5fa; }
  .conv-role.assistant { color: #34d399; }
  .conv-role.system { color: #a78bfa; }
  .conv-bubble.user { background: #1e3a5f; border: 1px solid #2563eb33; color: #e2e8f0; }
  .conv-bubble.assistant { background: #1a3a2a; border: 1px solid #10b98133; color: #e2e8f0; }
  .conv-bubble.system { background: #2d2150; border: 1px solid #7c3aed33; color: #c4b5fd; font-size: 12px; }
  .conv-system-box { background: #2d2150; border: 1px solid #7c3aed33; border-radius: 10px; margin-bottom: 20px; overflow: hidden; }
  .conv-system-toggle { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; cursor: pointer; user-select: none; }
  .conv-system-toggle:hover { background: #362668; }
  .conv-system-toggle .conv-role { margin-bottom: 0; }
  .conv-system-toggle .arrow { color: #a78bfa; font-size: 12px; transition: transform 0.2s; }
  .conv-system-toggle .arrow.open { transform: rotate(180deg); }
  .conv-system-content { padding: 0 16px 12px 16px; max-height: 300px; overflow-y: auto; font-size: 12px; color: #c4b5fd; white-space: pre-wrap; word-break: break-word; line-height: 1.6; display: none; }
  .conv-system-content.open { display: block; }
  .conv-context-note { font-size: 11px; color: #64748b; font-style: italic; padding: 4px 0 8px 4px; }
  .conv-tool-call { background: #1a2332; border: 1px solid #1e3a5f; border-radius: 8px; padding: 10px 14px; margin: 4px 0 8px 0; font-size: 12px; }
  .conv-tool-call .tool-name { color: #fbbf24; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
  .conv-tool-call .tool-args { color: #94a3b8; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 11px; margin-top: 4px; white-space: pre-wrap; word-break: break-all; }
  .conv-tool-result { background: #1a2332; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #94a3b8; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
  .conv-role.tool { color: #fbbf24; }
  .conv-thinking { background: #1c1917; border: 1px solid #44403c; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; font-size: 12px; color: #a8a29e; font-style: italic; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .conv-thinking-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #78716c; margin-bottom: 4px; }
  .conv-separator { border: none; border-top: 1px dashed #334155; margin: 20px 0; }
  .conv-trace-header { font-size: 11px; color: #64748b; margin-bottom: 12px; display: flex; gap: 16px; align-items: center; }
  .conv-trace-header .tag { background: #334155; padding: 2px 8px; border-radius: 4px; }
  .conv-empty { text-align: center; padding: 40px; color: #64748b; }
  .conv-nav { display: flex; gap: 8px; padding: 12px 20px; border-top: 1px solid #334155; flex-shrink: 0; }
  .conv-nav button { background: #334155; color: #e2e8f0; border: 1px solid #475569; padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; }
  .conv-nav button:hover { background: #475569; }
  .conv-nav button.active { background: #3b82f6; border-color: #3b82f6; }
  @media (max-width: 768px) { .charts { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="header">
  <h1>ROCK Gateway Dashboard</h1>
  <div class="header-controls">
    <select id="timeRange">
      <option value="1h">Last 1 hour</option>
      <option value="6h">Last 6 hours</option>
      <option value="24h" selected>Last 24 hours</option>
      <option value="7d">Last 7 days</option>
      <option value="all">All time</option>
    </select>
    <button id="autoRefreshBtn" onclick="toggleAutoRefresh()">Auto-refresh: OFF</button>
    <button onclick="refreshAll()">Refresh</button>
  </div>
</div>

<div class="container">
  <div class="cards" id="summaryCards">
    <div class="card"><div class="label">Total Requests</div><div class="value" id="totalReqs">-</div></div>
    <div class="card"><div class="label">Success Rate</div><div class="value success" id="successRate">-</div></div>
    <div class="card"><div class="label">Avg Latency</div><div class="value" id="avgLatency">-</div></div>
    <div class="card"><div class="label">Total Tokens</div><div class="value" id="totalTokens">-</div><div class="sublabel">Sum across all requests (model limit 262K per request)</div></div>
    <div class="card"><div class="label">Unique Users</div><div class="value" id="uniqueUsers">-</div></div>
  </div>

  <div class="charts">
    <div class="chart-box"><h3>Requests Over Time</h3><canvas id="timelineChart"></canvas></div>
    <div class="chart-box"><h3>Avg Latency Over Time</h3><canvas id="latencyChart"></canvas></div>
    <div class="chart-box full"><h3>Token Usage Over Time</h3><canvas id="tokenChart"></canvas></div>
  </div>

  <div class="table-box">
    <h3>Users</h3>
    <table>
      <thead><tr><th>User</th><th>Requests</th><th>Errors</th><th>Avg Latency</th><th>Total Tokens</th><th>Last Active</th></tr></thead>
      <tbody id="usersTable"><tr><td colspan="6" class="loading">Loading...</td></tr></tbody>
    </table>
  </div>

  <div class="table-box">
    <h3>Sessions</h3>
    <table>
      <thead><tr><th>Session</th><th>User</th><th>Started</th><th>Requests</th><th>Tokens</th><th>Avg Latency</th><th>Errors</th></tr></thead>
      <tbody id="sessionsTable"><tr><td colspan="7" class="loading">Loading...</td></tr></tbody>
    </table>
  </div>

  <div class="table-box">
    <h3>Recent Errors</h3>
    <table>
      <thead><tr><th>Trace ID</th><th>User</th><th>Timestamp</th><th>Error</th></tr></thead>
      <tbody id="errorsTable"><tr><td colspan="4" class="loading">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- Conversation Modal -->
<div class="modal-overlay" id="convModal">
  <div class="modal">
    <div class="modal-header">
      <div>
        <h2 id="convTitle">Conversation</h2>
        <div class="meta" id="convMeta"></div>
      </div>
      <button class="modal-close" onclick="closeConversation()">&times;</button>
    </div>
    <div class="conv-nav" id="convNav">
      <span style="font-size:12px; color:#64748b;">Each turn shows only new messages. System prompt shown once at top (click to expand).</span>
    </div>
    <div class="modal-body" id="convBody">
      <div class="conv-empty">Select a session or user to view conversations.</div>
    </div>
  </div>
</div>

<script>
let autoRefreshInterval = null;
let timelineChartInstance = null;
let latencyChartInstance = null;
let tokenChartInstance = null;

const chartColors = {
  success: 'rgba(52, 211, 153, 0.8)',
  error: 'rgba(248, 113, 113, 0.8)',
  latency: 'rgba(96, 165, 250, 0.8)',
  prompt: 'rgba(167, 139, 250, 0.8)',
  completion: 'rgba(251, 191, 36, 0.8)',
  grid: 'rgba(51, 65, 85, 0.5)',
  text: '#94a3b8',
};

function getTimeRange() {
  const val = document.getElementById('timeRange').value;
  if (val === 'all') return {};
  const now = new Date();
  const ms = {
    '1h': 3600000,
    '6h': 6 * 3600000,
    '24h': 24 * 3600000,
    '7d': 7 * 24 * 3600000,
  }[val] || 24 * 3600000;
  const start = new Date(now.getTime() - ms).toISOString();
  return { start };
}

function getInterval() {
  const val = document.getElementById('timeRange').value;
  return (val === '7d' || val === 'all') ? 'day' : 'hour';
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) return null;
  return resp.json();
}

function buildParams(extra = {}) {
  const range = getTimeRange();
  const params = new URLSearchParams();
  if (range.start) params.set('start', range.start);
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined && v !== null) params.set(k, v);
  }
  return params.toString();
}

function fmt(n) {
  if (n === null || n === undefined) return '-';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

function fmtMs(ms) {
  if (ms === null || ms === undefined) return '-';
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
  return Math.round(ms) + 'ms';
}

const TZ = 'Australia/Melbourne';

function fmtTime(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-AU', { timeZone: TZ, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return ts; }
}

function fmtTimeFull(ts) {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-AU', { timeZone: TZ, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ts; }
}

const defaultChartOpts = {
  responsive: true,
  maintainAspectRatio: true,
  plugins: { legend: { labels: { color: chartColors.text, font: { size: 11 } } } },
  scales: {
    x: { ticks: { color: chartColors.text, font: { size: 10 } }, grid: { color: chartColors.grid } },
    y: { ticks: { color: chartColors.text, font: { size: 10 } }, grid: { color: chartColors.grid }, beginAtZero: true },
  },
};

function fmtBucket(b) {
  if (!b) return b;
  try {
    const d = new Date(b.includes('T') ? b + 'Z' : b + 'T00:00:00Z');
    if (b.includes('T')) return d.toLocaleString('en-AU', { timeZone: TZ, month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString('en-AU', { timeZone: TZ, month: 'short', day: 'numeric' });
  } catch { return b; }
}

async function refreshStats() {
  const params = buildParams();
  const data = await fetchJSON('/v1/traces/stats?' + params);
  if (!data) return;
  document.getElementById('totalReqs').textContent = fmt(data.total);
  const rate = data.total > 0 ? ((data.success_count / data.total) * 100).toFixed(1) + '%' : '-';
  document.getElementById('successRate').textContent = rate;
  document.getElementById('avgLatency').textContent = fmtMs(data.avg_latency_ms);
  document.getElementById('totalTokens').textContent = fmt(data.total_tokens);
}

async function refreshUsers() {
  const params = buildParams();
  const data = await fetchJSON('/v1/traces/users?' + params);
  if (!data) return;
  document.getElementById('uniqueUsers').textContent = data.length;
  const tbody = document.getElementById('usersTable');
  if (data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="loading">No data</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(u => `<tr>
    <td><strong class="clickable" onclick="openConversation({user_id: '${u.user_id}'})">${u.user_id}</strong></td>
    <td>${fmt(u.request_count)}</td>
    <td>${u.error_count > 0 ? '<span class="badge badge-error">' + u.error_count + '</span>' : '0'}</td>
    <td>${fmtMs(u.avg_latency_ms)}</td>
    <td>${fmt(u.total_tokens)}</td>
    <td class="mono">${fmtTime(u.last_active)}</td>
  </tr>`).join('');
}

async function refreshSessions() {
  const params = buildParams({ limit: 20 });
  const data = await fetchJSON('/v1/traces/sessions?' + params);
  if (!data) return;
  const tbody = document.getElementById('sessionsTable');
  if (data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading">No sessions</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(s => `<tr>
    <td class="mono clickable" onclick="openConversation({session_id: '${s.session_id}', title: '${s.user_id} — ${s.session_id.substring(0,8)}'})">${s.session_id.substring(0, 8)}...</td>
    <td>${s.user_id}</td>
    <td class="mono">${fmtTime(s.start_time)}</td>
    <td>${s.request_count}</td>
    <td>${fmt(s.total_tokens)}</td>
    <td>${fmtMs(s.avg_latency_ms)}</td>
    <td>${s.error_count > 0 ? '<span class="badge badge-error">' + s.error_count + '</span>' : '<span class="badge badge-success">0</span>'}</td>
  </tr>`).join('');
}

async function refreshErrors() {
  const params = buildParams({ status: 'error', limit: 10 });
  const data = await fetchJSON('/v1/traces?' + params);
  if (!data) return;
  const tbody = document.getElementById('errorsTable');
  const traces = data.traces || [];
  if (traces.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" class="loading">No errors</td></tr>';
    return;
  }
  tbody.innerHTML = traces.map(t => `<tr>
    <td class="mono">${t.trace_id.substring(0, 8)}...</td>
    <td>${t.user_id}</td>
    <td class="mono">${fmtTime(t.timestamp)}</td>
    <td>${t.error || '-'}</td>
  </tr>`).join('');
}

async function refreshTimeline() {
  const interval = getInterval();
  const params = buildParams({ interval });
  const data = await fetchJSON('/v1/traces/timeline?' + params);
  if (!data || data.length === 0) return;

  const labels = data.map(d => fmtBucket(d.bucket));

  // Timeline chart
  if (timelineChartInstance) timelineChartInstance.destroy();
  timelineChartInstance = new Chart(document.getElementById('timelineChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Success', data: data.map(d => d.success_count), backgroundColor: chartColors.success },
        { label: 'Error', data: data.map(d => d.error_count), backgroundColor: chartColors.error },
      ],
    },
    options: { ...defaultChartOpts, scales: { ...defaultChartOpts.scales, x: { ...defaultChartOpts.scales.x, stacked: true }, y: { ...defaultChartOpts.scales.y, stacked: true } } },
  });

  // Latency chart
  if (latencyChartInstance) latencyChartInstance.destroy();
  latencyChartInstance = new Chart(document.getElementById('latencyChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Avg Latency (ms)', data: data.map(d => d.avg_latency_ms), borderColor: chartColors.latency, backgroundColor: 'rgba(96, 165, 250, 0.1)', fill: true, tension: 0.3 }],
    },
    options: defaultChartOpts,
  });

  // Token chart
  if (tokenChartInstance) tokenChartInstance.destroy();
  tokenChartInstance = new Chart(document.getElementById('tokenChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Prompt Tokens', data: data.map(d => d.total_prompt_tokens), backgroundColor: chartColors.prompt },
        { label: 'Completion Tokens', data: data.map(d => d.total_completion_tokens), backgroundColor: chartColors.completion },
      ],
    },
    options: { ...defaultChartOpts, scales: { ...defaultChartOpts.scales, x: { ...defaultChartOpts.scales.x, stacked: true }, y: { ...defaultChartOpts.scales.y, stacked: true } } },
  });
}

async function refreshAll() {
  await Promise.all([refreshStats(), refreshUsers(), refreshSessions(), refreshErrors(), refreshTimeline()]);
}

function toggleAutoRefresh() {
  const btn = document.getElementById('autoRefreshBtn');
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
    btn.textContent = 'Auto-refresh: OFF';
    btn.classList.remove('active');
  } else {
    autoRefreshInterval = setInterval(refreshAll, 30000);
    btn.textContent = 'Auto-refresh: ON';
    btn.classList.add('active');
  }
}

document.getElementById('timeRange').addEventListener('change', refreshAll);
refreshAll();

// --- Conversation Viewer ---
let currentConvData = null;

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function openConversation(opts) {
  const params = new URLSearchParams();
  if (opts.session_id) params.set('session_id', opts.session_id);
  if (opts.user_id) params.set('user_id', opts.user_id);
  if (opts.trace_id) params.set('trace_id', opts.trace_id);
  params.set('limit', '50');

  const data = await fetchJSON('/v1/traces/conversation?' + params.toString());
  if (!data) return;

  currentConvData = data;
  const title = opts.title || (opts.session_id ? 'Session ' + opts.session_id.substring(0,8) + '...' : 'Conversations for ' + (opts.user_id || 'unknown'));
  document.getElementById('convTitle').textContent = title;

  const totalTokens = data.reduce((s, t) => s + (t.token_usage?.total_tokens || 0), 0);
  const meta = `${data.length} request(s) | ${fmt(totalTokens)} tokens`;
  document.getElementById('convMeta').textContent = meta;

  renderConversation();
  document.getElementById('convModal').classList.add('open');
}

function closeConversation() {
  document.getElementById('convModal').classList.remove('open');
  currentConvData = null;
}

function parseThinking(content) {
  if (!content) return { thinking: '', output: '' };
  // Handle <think>...</think> tags from Qwen
  const thinkMatch = content.match(/^([\s\S]*?)<\/think>\s*([\s\S]*)$/);
  if (thinkMatch) {
    let thinking = thinkMatch[1].replace(/^<think>\s*/, '').trim();
    let output = thinkMatch[2].trim();
    return { thinking, output };
  }
  // No think tags
  return { thinking: '', output: content };
}

function renderAssistantMsg(content, toolCalls) {
  let html = '<div class="conv-turn"><div class="conv-role assistant">assistant</div>';

  const { thinking, output } = parseThinking(content);

  if (thinking) {
    html += `<div class="conv-thinking"><div class="conv-thinking-label">Thinking</div>${escapeHtml(thinking)}</div>`;
  }
  if (output) {
    html += `<div class="conv-bubble assistant">${escapeHtml(output)}</div>`;
  }
  if (toolCalls && toolCalls.length > 0) {
    toolCalls.forEach(tc => {
      let argsDisplay = tc.arguments || '';
      try { argsDisplay = JSON.stringify(JSON.parse(argsDisplay), null, 2); } catch {}
      html += `<div class="conv-tool-call">
        <span class="tool-name">${escapeHtml(tc.name || 'unknown_tool')}</span>
        <div class="tool-args">${escapeHtml(argsDisplay)}</div>
      </div>`;
    });
  }
  if (!thinking && !output && (!toolCalls || toolCalls.length === 0)) {
    html += '<div class="conv-bubble assistant" style="color:#64748b">(empty response)</div>';
  }
  html += '</div>';
  return html;
}

function renderConversation() {
  const body = document.getElementById('convBody');
  if (!currentConvData || currentConvData.length === 0) {
    body.innerHTML = '<div class="conv-empty">No conversation data found.</div>';
    return;
  }

  let html = '';

  // Extract system message from the first trace (shown once at the top)
  const firstMessages = currentConvData[0].messages || [];
  const systemMsgs = firstMessages.filter(m => m.role === 'system');
  if (systemMsgs.length > 0) {
    const sysContent = systemMsgs.map(m => m.content || '').join('\\n\\n');
    html += `<div class="conv-system-box">
      <div class="conv-system-toggle" onclick="toggleSystemMsg()">
        <div class="conv-role system" style="margin:0">System Prompt</div>
        <span class="arrow" id="sysArrow">&#9660;</span>
      </div>
      <div class="conv-system-content" id="sysContent">${escapeHtml(sysContent)}</div>
    </div>`;
  }

  // Track previously seen message count to compute deltas
  let prevMsgCount = 0;

  currentConvData.forEach((trace, idx) => {
    if (idx > 0) html += '<hr class="conv-separator">';

    const tokens = trace.token_usage?.total_tokens || 0;
    const promptTokens = trace.token_usage?.prompt_tokens || 0;
    const hasToolCalls = (trace.assistant_tool_calls && trace.assistant_tool_calls.length > 0);
    const turnType = hasToolCalls ? 'Tool Use' : 'Response';
    html += `<div class="conv-trace-header">
      <span class="tag">Turn ${idx + 1} — ${turnType}</span>
      <span>${fmtTimeFull(trace.timestamp)}</span>
      <span>${fmtMs(trace.latency_ms)}</span>
      <span>${fmt(tokens)} tokens (${fmt(promptTokens)} prompt)</span>
      ${trace.status === 'error' ? '<span class="badge badge-error">ERROR</span>' : ''}
    </div>`;

    const messages = trace.messages || [];
    // Filter out system messages (already shown at top)
    const nonSystemMsgs = messages.filter(m => m.role !== 'system');

    // Compute new messages (delta from previous trace)
    const newMsgs = nonSystemMsgs.slice(prevMsgCount);

    if (newMsgs.length === 0 && idx > 0) {
      // No new user messages — might be a retry or same context
      html += '<div class="conv-context-note">* Same context as previous turn</div>';
    }

    // Show only the new messages
    newMsgs.forEach(msg => {
      const role = msg.role || 'unknown';
      if (role === 'tool') {
        // Tool result — show truncated
        const content = msg.content || '';
        const truncated = content.length > 500 ? content.substring(0, 500) + '\\n... [' + content.length + ' chars]' : content;
        html += `<div class="conv-turn">
          <div class="conv-role tool">tool result</div>
          <div class="conv-tool-result">${escapeHtml(truncated)}</div>
        </div>`;
      } else if (role === 'assistant') {
        // Assistant message from history — may contain tool calls
        html += renderAssistantMsg(msg.content, msg.tool_calls);
      } else {
        const roleClass = role === 'user' ? 'user' : 'system';
        html += `<div class="conv-turn">
          <div class="conv-role ${roleClass}">${escapeHtml(role)}</div>
          <div class="conv-bubble ${roleClass}">${escapeHtml(msg.content || '')}</div>
        </div>`;
      }
    });

    // Show assistant reply from the response (the NEW reply for this turn)
    if (trace.assistant_reply || (trace.assistant_tool_calls && trace.assistant_tool_calls.length > 0)) {
      html += renderAssistantMsg(trace.assistant_reply, trace.assistant_tool_calls);
    }

    if (trace.error) {
      html += `<div class="conv-turn">
        <div class="conv-role" style="color:#f87171">error</div>
        <div class="conv-bubble" style="background:#450a0a;border-color:#7f1d1d33;color:#fca5a5">${escapeHtml(trace.error)}</div>
      </div>`;
    }

    // Update prevMsgCount: non-system messages in this trace + the assistant reply we just showed
    prevMsgCount = nonSystemMsgs.length + (trace.assistant_reply ? 1 : 0);
  });

  body.innerHTML = html;
}

function toggleSystemMsg() {
  const content = document.getElementById('sysContent');
  const arrow = document.getElementById('sysArrow');
  content.classList.toggle('open');
  arrow.classList.toggle('open');
}

// Close modal on overlay click
document.getElementById('convModal').addEventListener('click', function(e) {
  if (e.target === this) closeConversation();
});

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeConversation();
});
</script>
</body>
</html>"""


@dashboard_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the trace visualization dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)

/* Monitoring & Analytics */
'use strict';

(async function initAnalytics() {
  await Shell.mount('analytics');

  const $ = (id) => document.getElementById(id);
  let agents = [];
  let analytics = null;
  let sessions = [];
  const filters = { status: 'all', days: 30, agentId: '' };

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '07 — Monitoring & Analytics',
    title: 'Operational Dashboard',
    sub: 'All values are derived from stored sessions and events — no fake production metrics. Filters work across totals, latency, providers and sessions.',
    right: `<select class="select input-sm w-auto" id="filter-status" aria-label="Filter sessions by status">
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="completed">Completed</option>
        <option value="interrupted">Interrupted</option>
        <option value="error">Error</option>
      </select>
      <select class="select input-sm w-auto" id="filter-days" aria-label="Filter by time range">
        <option value="1">Last 24 hours</option>
        <option value="7">Last 7 days</option>
        <option value="30" selected>Last 30 days</option>
        <option value="90">Last 90 days</option>
        <option value="365">Last 365 days</option>
      </select>
      <select class="select input-sm w-auto" id="filter-agent" aria-label="Filter by agent">
        <option value="">All agents</option>
      </select>
      <button class="btn btn-dark btn-xs" id="refresh-analytics" type="button">Refresh</button>`,
  });
  $('modal-close').innerHTML = Shell.icon('x', 'w-3.5 h-3.5');

  // ---- helpers -----------------------------------------------------------

  const SECTION_ORDER = { stt: 0, llm: 1, tts: 2 };

  function pct(part, total) {
    return total ? Math.round((part / total) * 100) : 0;
  }

  function eventColor(type) {
    if (type === 'error') return '#ef4444';
    if (type === 'barge_in') return '#f59e0b';
    if (type === 'transfer_request') return '#8b5cf6';
    if (type === 'session_ended') return '#94a3b8';
    if (type === 'session_started' || type === 'greeting') return '#10b981';
    return '#3b82f6';
  }

  function eventSummary(ev) {
    const p = ev.payload || {};
    if (ev.type === 'error') return p.message || 'Session error';
    if (p.intent) return `${p.intent}${p.latencyMs ? ` • ${p.latencyMs} ms` : ''}`;
    if (p.reason) return p.reason;
    if (p.mode) return p.mode;
    if (p.text) return String(p.text).slice(0, 90);
    if (p.count !== undefined) return `count ${p.count}`;
    const keys = Object.keys(p);
    return keys.length ? JSON.stringify(p).slice(0, 90) : '';
  }

  function agentLabel(id) {
    const a = agents.find((x) => x.id === id);
    return a ? a.name : 'Deleted agent';
  }

  function e2eOf(session) {
    if (session.latencyMetrics?.lastE2E) return Math.round(session.latencyMetrics.lastE2E);
    const assistant = [...(session.turns || [])].reverse().find((t) => t.role === 'assistant' && t.latencyMs);
    return assistant?.latencyMs ?? null;
  }

  // ---- render ------------------------------------------------------------

  function renderStats() {
    const totals = analytics?.totals || {};
    $('stat-total').textContent = totals.total ?? '—';
    $('stat-completed').textContent = totals.completed ?? '—';
    $('stat-completed-pct').textContent = `${pct(totals.completed || 0, totals.total || 0)}% completion`;
    $('stat-interrupted').textContent = totals.interrupted ?? '—';
    $('stat-errors').textContent = totals.errors ?? '—';
  }

  function renderLatency() {
    const lat = analytics?.latencies || {};
    const val = (v) => (v === null || v === undefined ? '—' : Math.round(v));
    $('lat-p50').textContent = val(lat.p50);
    $('lat-p90').textContent = val(lat.p90);
    $('lat-p95').textContent = val(lat.p95);
    $('latency-sample').textContent = `${lat.sampleSize ?? 0} turns`;
    $('data-samples').textContent = String(lat.sampleSize ?? 0);
    $('data-generated').textContent = analytics ? UI.fmtTime(analytics.generatedAt) : '—';
  }

  function renderVolume() {
    const daily = analytics?.daily || {};
    const days = [];
    const today = new Date();
    for (let i = 13; i >= 0; i -= 1) {
      const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
      const key = d.toISOString().slice(0, 10);
      days.push({ key, label: `${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`, count: daily[key] || 0 });
    }
    const max = Math.max(1, ...days.map((d) => d.count));
    const total = days.reduce((sum, d) => sum + d.count, 0);
    $('volume-total').textContent = `${total} sessions`;
    $('volume-chart').innerHTML = days.map((d) => `<div class="chart-bar-col" title="${d.key}: ${d.count} sessions">
      <div class="chart-bar-track"><div class="chart-bar" style="height:${Math.max(d.count ? 6 : 2, Math.round((d.count / max) * 100))}%"></div></div>
      <div class="chart-label">${d.count || ''}</div>
    </div>`).join('');
    $('volume-labels').innerHTML = `<span>${days[0].label}</span><span>${days[6].label}</span><span>${days[13].label}</span>`;
  }

  function renderIntentMix() {
    const counts = new Map();
    sessions.forEach((s) => {
      (s.turns || []).forEach((t) => {
        if (t.role === 'user' && t.intent) counts.set(t.intent, (counts.get(t.intent) || 0) + 1);
      });
    });
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    if (!sorted.length) {
      $('intent-mix').innerHTML = '<div class="text-[9px] text-slate-400">No intents recorded yet.</div>';
      return;
    }
    const max = Math.max(...sorted.map((x) => x[1]));
    $('intent-mix').innerHTML = sorted.map(([intent, count]) => `<div class="flex items-center gap-2">
      <span class="w-[86px] flex-none truncate font-mono text-[8.5px] text-slate-600">${UI.esc(intent)}</span>
      <div class="progress flex-1"><span style="width:${Math.round((count / max) * 100)}%"></span></div>
      <span class="w-5 flex-none text-right font-mono text-[8.5px] text-slate-500">${count}</span>
    </div>`).join('');
  }

  function renderProviders() {
    const stats = analytics?.providerStats || [];
    $('provider-count').textContent = `${stats.length} adapters`;
    if (!stats.length) {
      $('provider-list').innerHTML = '<div class="text-[9px] text-slate-400">No providers registered.</div>';
      return;
    }
    const ordered = [...stats].sort((a, b) => (SECTION_ORDER[a.type] ?? 9) - (SECTION_ORDER[b.type] ?? 9) || a.name.localeCompare(b.name));
    $('provider-list').innerHTML = ordered.map((p) => {
      const bad = Number(String(p.failureRate).replace('%', '')) > 0;
      return `<div class="rounded-lg border border-slate-200 px-2.5 py-1.5">
        <div class="flex items-center justify-between gap-1.5">
          <span class="min-w-0 truncate text-[10px] font-bold text-slate-800" title="${UI.attr(p.name)}">${UI.esc(p.name)}</span>
          <div class="flex flex-none items-center gap-1">
            <span class="pill ${bad ? 'pill-red' : 'pill-gray'} no-dot">${UI.esc(p.failureRate)} fail</span>
            ${UI.statusPill(p.status)}
          </div>
        </div>
        <div class="mt-0.5 flex items-center justify-between text-[8px] text-slate-400">
          <span>${UI.providerTypeLabel(p.type)}</span>
          <span>${p.total} session${p.total === 1 ? '' : 's'} · ${p.failures} failure${p.failures === 1 ? '' : 's'}</span>
        </div>
      </div>`;
    }).join('');
  }

  function renderAgentMix() {
    const byAgent = analytics?.byAgent || {};
    const entries = Object.entries(byAgent).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      $('agent-mix').innerHTML = '<div class="text-[9px] text-slate-400">No sessions yet.</div>';
      return;
    }
    const max = Math.max(...entries.map((e) => e[1]));
    $('agent-mix').innerHTML = entries.map(([id, count]) => `<button class="block w-full text-left" data-agent-filter="${id}" type="button" title="Filter dashboard by this agent">
      <div class="flex items-center justify-between gap-2">
        <span class="min-w-0 truncate text-[9.5px] font-semibold text-slate-600">${UI.esc(agentLabel(id))}</span>
        <span class="font-mono text-[8.5px] text-slate-400">${count}</span>
      </div>
      <div class="progress mt-1"><span style="width:${Math.round((count / max) * 100)}%"></span></div>
    </button>`).join('');
  }

  function renderSessionTable() {
    $('session-table-count').textContent = `${sessions.length} shown`;
    if (!sessions.length) {
      $('sessions-body').innerHTML = '<tr><td colspan="8" class="py-8 text-center text-[10px] text-slate-400">No sessions match these filters.</td></tr>';
      return;
    }
    $('sessions-body').innerHTML = sessions.map((s) => `<tr class="cursor-pointer" data-open-session="${s.id}">
      <td>
        <div class="text-[10px] font-semibold text-slate-700">${UI.fmtDate(s.startedAt)}</div>
        <div class="text-[8px] text-slate-400">${UI.timeAgo(s.startedAt)}</div>
      </td>
      <td><div class="max-w-[170px] truncate text-[10px] font-medium text-slate-700" title="${UI.attr(agentLabel(s.agentId))}">${UI.esc(agentLabel(s.agentId))}</div></td>
      <td><span class="chip">${UI.esc(s.userInputMode)}</span></td>
      <td>${UI.statusPill(s.status)}</td>
      <td class="font-mono text-[9.5px]">${s.turnCount ?? 0}</td>
      <td class="font-mono text-[9.5px]">${e2eOf(s) !== null ? `${e2eOf(s)} ms` : '—'}</td>
      <td><span class="chip chip-mono">${UI.shortId(s.id)}</span></td>
      <td class="text-right"><button class="btn btn-xs btn-outline" data-open-session="${s.id}" type="button">Inspect</button></td>
    </tr>`).join('');
  }

  function renderAll() {
    renderStats();
    renderLatency();
    renderVolume();
    renderIntentMix();
    renderProviders();
    renderAgentMix();
    renderSessionTable();
  }

  // ---- load --------------------------------------------------------------

  async function load() {
    const params = new URLSearchParams();
    if (filters.status !== 'all') params.set('status', filters.status);
    if (filters.agentId) params.set('agentId', filters.agentId);
    params.set('days', String(filters.days));
    const sessionParams = new URLSearchParams();
    sessionParams.set('limit', '200');
    if (filters.status !== 'all') sessionParams.set('status', filters.status);
    if (filters.agentId) sessionParams.set('agentId', filters.agentId);

    const [an, ss] = await Promise.all([
      API.analytics(`?${params.toString()}`),
      API.sessions(`?${sessionParams.toString()}`),
    ]);
    analytics = an;
    const since = Date.now() - filters.days * 86400000;
    sessions = ss
      .filter((s) => new Date(s.startedAt).getTime() >= since)
      .sort((a, b) => new Date(b.startedAt) - new Date(a.startedAt));
    renderAll();
  }

  async function safeLoad(showBusy = false) {
    const btn = $('refresh-analytics');
    if (showBusy) {
      btn.disabled = true;
      btn.innerHTML = '<svg class="spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg> Refresh';
    }
    try {
      await load();
    } catch (err) {
      UI.toast(err.message, 'error');
      $('sessions-body').innerHTML = `<tr><td colspan="8" class="py-8 text-center text-[10px] text-red-600">${UI.esc(err.message)}</td></tr>`;
    } finally {
      if (showBusy) {
        btn.disabled = false;
        btn.textContent = 'Refresh';
      }
    }
  }

  // ---- session inspector -------------------------------------------------

  function openModal() {
    $('session-modal').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    $('session-modal').classList.add('hidden');
    document.body.style.overflow = '';
  }

  async function inspectSession(id) {
    openModal();
    $('modal-title').textContent = 'Loading session…';
    $('modal-sub').textContent = id;
    $('modal-body').innerHTML = '<div class="py-10 text-center text-[10px] text-slate-400">Reading persisted transcript and events…</div>';
    try {
      const s = await API.session(id);
      $('modal-title').textContent = agentLabel(s.agentId);
      $('modal-sub').textContent = `${s.id} • started ${UI.fmtDate(s.startedAt)}`;
      const metrics = s.latencyMetrics || {};
      const duration = s.endedAt ? Math.max(0, new Date(s.endedAt) - new Date(s.startedAt)) : null;
      const turns = s.turns || [];
      const events = s.events || [];
      $('modal-body').innerHTML = `
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div class="label mb-0.5">Status</div>${UI.statusPill(s.status)}
          </div>
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div class="label mb-0.5">Mode</div><div class="text-[10.5px] font-bold text-slate-700">${UI.esc(s.userInputMode)}</div>
          </div>
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div class="label mb-0.5">Turns</div><div class="mono text-[13px] font-bold text-slate-800">${s.turnCount ?? 0}</div>
          </div>
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2">
            <div class="label mb-0.5">Duration</div><div class="mono text-[11px] font-bold text-slate-800">${duration === null ? 'live' : UI.duration(duration)}</div>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-1">
          <span class="chip chip-mono">stage: ${UI.esc(s.state?.stage || 'start')}</span>
          <span class="chip chip-mono">ended: ${s.state?.ended ? 'yes' : 'no'}</span>
          <span class="chip chip-mono">reason: ${UI.esc(s.state?.reason || '—')}</span>
          <span class="chip chip-mono">consent: ${s.state?.consent ? 'yes' : 'no'}</span>
          <span class="chip chip-mono">barge-ins: ${s.state?.bargeIns ?? 0}</span>
          <span class="chip chip-mono">e2e: ${metrics.lastE2E ? `${Math.round(metrics.lastE2E)} ms` : '—'}</span>
          <span class="chip chip-mono">stt: ${metrics.lastSTT ? `${Math.round(metrics.lastSTT)} ms` : '—'}</span>
          <span class="chip chip-mono">tts: ${metrics.lastTTS ? `${Math.round(metrics.lastTTS)} ms` : '—'}</span>
        </div>
        ${s.errorMessage ? `<div class="mt-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-2 text-[9.5px] text-red-700">${UI.esc(s.errorMessage)}</div>` : ''}
        <div class="mt-3 grid gap-3 lg:grid-cols-2">
          <div class="rounded-xl border border-slate-200">
            <div class="border-b border-slate-100 px-3 py-2 text-[10px] font-extrabold uppercase tracking-[0.08em] text-slate-500">Transcript</div>
            <div class="max-h-[46vh] overflow-y-auto p-3">
              ${turns.length ? turns.map((t) => `<div class="turn-row ${t.role === 'user' ? 'turn-user' : 'turn-agent'}">
                <div class="turn-avatar">${t.role === 'user' ? 'U' : 'A'}</div>
                <div class="min-w-0 max-w-[92%]">
                  <div class="turn-bubble" style="white-space:pre-wrap">${UI.esc(t.content)}</div>
                  <div class="turn-meta">${[t.intent, t.latencyMs ? `${t.latencyMs} ms` : '', UI.fmtTime(t.createdAt)].filter(Boolean).join(' • ')}</div>
                </div>
              </div>`).join('') : '<div class="text-[9.5px] text-slate-400">No turns.</div>'}
            </div>
          </div>
          <div class="rounded-xl border border-slate-200">
            <div class="border-b border-slate-100 px-3 py-2 text-[10px] font-extrabold uppercase tracking-[0.08em] text-slate-500">Events</div>
            <div class="max-h-[46vh] overflow-y-auto p-3">
              ${events.length ? events.map((ev) => `<div class="event-row">
                <span class="event-dot" style="background:${eventColor(ev.type)}"></span>
                <div class="min-w-0 flex-1">
                  <div class="event-type">${UI.esc(ev.type)}</div>
                  <div class="truncate text-[8.5px] text-slate-500">${UI.esc(eventSummary(ev))}</div>
                </div>
                <span class="event-ts">${UI.fmtTime(ev.ts)}</span>
              </div>`).join('') : '<div class="text-[9.5px] text-slate-400">No events.</div>'}
            </div>
          </div>
        </div>`;
    } catch (err) {
      $('modal-title').textContent = 'Session unavailable';
      $('modal-body').innerHTML = `<div class="rounded-lg border border-red-200 bg-red-50 p-3 text-[10px] text-red-700">${UI.esc(err.message)}</div>`;
      UI.toast(err.message, 'error');
    }
  }

  // ---- events ------------------------------------------------------------

  $('filter-status').addEventListener('change', (event) => {
    filters.status = event.target.value;
    safeLoad();
  });
  $('filter-days').addEventListener('change', (event) => {
    filters.days = Number(event.target.value);
    safeLoad();
  });
  $('filter-agent').addEventListener('change', (event) => {
    filters.agentId = event.target.value;
    safeLoad();
  });
  $('refresh-analytics').addEventListener('click', () => safeLoad(true));

  $('agent-mix').addEventListener('click', (event) => {
    const btn = event.target.closest('[data-agent-filter]');
    if (!btn) return;
    filters.agentId = btn.dataset.agentFilter;
    $('filter-agent').value = filters.agentId;
    safeLoad();
  });

  $('sessions-body').addEventListener('click', (event) => {
    const target = event.target.closest('[data-open-session]');
    if (!target) return;
    inspectSession(target.dataset.openSession);
  });

  $('modal-close').addEventListener('click', closeModal);
  $('session-modal').addEventListener('click', (event) => {
    if (event.target.closest('[data-close-modal]')) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('session-modal').classList.contains('hidden')) closeModal();
  });

  // ---- boot --------------------------------------------------------------

  try {
    agents = await API.agents();
  } catch {
    agents = [];
  }
  $('filter-agent').innerHTML = '<option value="">All agents</option>' + agents
    .map((a) => `<option value="${a.id}">${UI.esc(a.name)}</option>`).join('');

  await safeLoad();
})();

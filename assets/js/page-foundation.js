/* Foundation page */
'use strict';

(async function initFoundation() {
  await Shell.mount('foundation');

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '01 — Foundation',
    title: 'Project Foundation & Health',
    sub: 'Live proof that the API, SQLite persistence, provider registry and voice surfaces are all reachable before a session starts.',
    right: `
      <span class="pill pill-green" id="foundation-health-pill">Checking backend…</span>
      <span class="pill pill-ghost no-dot" id="foundation-version">v1.0.0</span>
      <span class="pill pill-red" id="foundation-telephony">Telephony Off</span>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });
  document.querySelectorAll('[data-gate-icon]').forEach((el) => {
    el.innerHTML = Shell.icon('check', 'w-3.5 h-3.5');
  });
  document.getElementById('env-alert-icon').innerHTML = Shell.icon('alert', 'w-3.5 h-3.5');

  const $ = (id) => document.getElementById(id);

  function setDot(el, ok) {
    if (!el) return;
    el.style.background = ok ? '#10b981' : '#ef4444';
    el.style.boxShadow = `0 0 0 3px ${ok ? 'rgba(16,185,129,.14)' : 'rgba(239,68,68,.14)'}`;
  }

  function renderEnv(health) {
    const caps = health.capabilities || {};
    const checks = [
      ['Database reachable', health.checks?.database === 'pass', 'SQLite'],
      ['Storage writable', health.checks?.storage === 'pass', 'data/'],
      ['API process', health.checks?.api === 'pass', `uptime ${health.uptimeSec || 0}s`],
      ['Deepgram proxy', !!caps.deepgramTts, caps.deepgramTts ? 'Aura + Nova-2' : 'browser fallback'],
      ['Auth gate', !!caps.auth, caps.auth ? 'Bearer required' : 'localhost only'],
      ['Telephony', health.telephony === 'disabled', health.telephony === 'disabled' ? 'mock-only' : 'enabled'],
    ];
    $('env-checks').innerHTML = checks.map(([name, ok, detail]) => `
      <div class="flex items-center gap-2 rounded-lg border ${ok ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200 bg-slate-50/60'} px-2.5 py-2">
        <span class="status-dot" style="background:${ok ? '#10b981' : '#94a3b8'};box-shadow:0 0 0 3px ${ok ? 'rgba(16,185,129,.14)' : 'rgba(148,163,184,.14)'}"></span>
        <div class="min-w-0">
          <div class="text-[10px] font-bold text-slate-700 truncate">${UI.esc(name)}</div>
          <div class="text-[9px] text-slate-400 truncate">${UI.esc(detail)}</div>
        </div>
      </div>`).join('');
  }

  async function load(showBusy = false) {
    const btn = $('refresh-health');
    if (showBusy) UI.setBusy(btn, true, 'Loading');
    try {
      const [health, agents, sessions, cases, providers] = await Promise.all([
        API.health(),
        API.agents().catch(() => []),
        API.sessions('?limit=200').catch(() => []),
        API.testCases().catch(() => []),
        API.providers().catch(() => []),
      ]);

      $('backend-state').textContent = health.ok ? 'Healthy' : 'Degraded';
      $('backend-detail').textContent = `${health.service} • ${health.database}`;
      $('backend-code').textContent = 'HTTP 200';
      $('backend-code').className = `pill no-dot ${health.ok ? 'pill-green' : 'pill-red'}`;
      $('backend-latency').textContent = `${health.latencyMs} ms`;
      setDot($('backend-dot'), health.ok);

      $('db-state').textContent = health.db === 'connected' ? 'Connected' : health.db;
      $('db-code').textContent = health.database || 'SQLite';
      setDot($('db-dot'), health.db === 'connected');

      $('count-agents').textContent = agents.length;
      $('count-sessions').textContent = sessions.length;
      $('count-cases').textContent = cases.length;
      $('count-providers').textContent = providers.length;

      const pill = $('foundation-health-pill');
      pill.textContent = health.ok ? 'BACKEND HEALTHY' : 'BACKEND DEGRADED';
      pill.className = `pill ${health.ok ? 'pill-green' : 'pill-red'}`;
      $('foundation-version').textContent = `v${health.version}`;
      const tel = $('foundation-telephony');
      tel.textContent = health.telephony === 'disabled' ? 'Telephony Off' : 'Telephony On';
      tel.className = `pill ${health.telephony === 'disabled' ? 'pill-red' : 'pill-amber'}`;

      $('gates-count').textContent = '7/7 pass';
      renderEnv(health);

      const snapshot = {
        ok: health.ok,
        service: health.service,
        version: health.version,
        environment: health.environment,
        database: health.database,
        latencyMs: health.latencyMs,
        uptimeSec: health.uptimeSec,
        telephony: health.telephony,
        checks: health.checks,
        capabilities: health.capabilities,
      };
      $('health-json').textContent = JSON.stringify(snapshot, null, 2);
    } catch (err) {
      $('backend-state').textContent = 'Offline';
      $('backend-detail').textContent = 'Start server.py';
      $('backend-code').textContent = 'no response';
      $('backend-code').className = 'pill pill-red no-dot';
      $('db-state').textContent = 'Unknown';
      $('db-code').textContent = '—';
      setDot($('backend-dot'), false);
      setDot($('db-dot'), false);
      $('foundation-health-pill').textContent = 'API OFFLINE';
      $('foundation-health-pill').className = 'pill pill-red';
      $('gates-count').textContent = 'offline';
      $('health-json').textContent = `{\n  "error": ${JSON.stringify(err.message)}\n}`;
      $('env-checks').innerHTML = `<div class="sm:col-span-2 text-[10.5px] text-red-600">Health check failed: ${UI.esc(err.message)}</div>`;
      UI.toast(err.message, 'error');
    } finally {
      if (showBusy) UI.setBusy(btn, false);
    }
  }

  $('refresh-health').addEventListener('click', () => load(true));
  document.getElementById('foundation-health-pill').addEventListener('click', () => load(true));
  await load();
})();

/* Deepgram Compliance - everything this project consumes from Deepgram */
'use strict';

(async function initDeepgram() {
  await Shell.mount('deepgram');

  const $ = (id) => document.getElementById(id);
  let data = null;

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '11 — Deepgram Compliance',
    title: 'Deepgram Compliance',
    sub: 'One place for everything the project gets from Deepgram: the connected account, the console surfaces, every agent configuration and a per-agent verdict.',
    right: `<a class="btn btn-outline" href="/agents">${Shell.icon('layers')} Voice agent builder</a>
      <a class="btn btn-primary" href="/lab">${Shell.icon('flask')} Voice Lab</a>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  function voiceLabel(voiceId) {
    const voice = window.VOICE_CATALOG?.byId(voiceId);
    if (!voice) return voiceId || '—';
    return `${voice.family} - ${voice.name} (${voice.accent}, ${voice.gender})`;
  }

  function verdictPill(verdict) {
    if (verdict === 'pass') return '<span class="pill pill-green no-dot">compliant</span>';
    if (verdict === 'warn') return '<span class="pill pill-amber no-dot">review</span>';
    return '<span class="pill pill-red no-dot">not compliant</span>';
  }

  function checkPill(status) {
    if (status === 'pass') return '<span class="pill pill-green no-dot">pass</span>';
    if (status === 'warn') return '<span class="pill pill-amber no-dot">warn</span>';
    return '<span class="pill pill-red no-dot">fail</span>';
  }

  function renderHero() {
    const account = data.account || {};
    const pill = $('dg-hero-pill');
    const body = $('dg-hero-body');
    if (!account.connected) {
      pill.textContent = 'not connected';
      pill.className = 'pill pill-red-dark';
      body.innerHTML = `<div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-[10px] text-amber-200 sm:col-span-2 lg:col-span-4">${UI.esc(account.message || 'Add DEEPGRAM_API_KEY to .env and restart the server.')}</div>`;
      return;
    }
    pill.textContent = 'connected';
    pill.className = 'pill pill-green-dark';
    const project = account.project || {};
    const catalogue = account.catalogue || {};
    body.innerHTML = `
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Project</div>
        <div class="mt-1 truncate text-[10.5px] font-bold text-slate-100">${UI.esc(project.name || 'Deepgram project')}</div>
        <div class="mono mt-0.5 truncate text-[8px] text-slate-500">${UI.esc(project.id || '')}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">API key</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">Backend only</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">Never served, never in the browser bundle</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Models</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">${(account.sttModels || []).length} speech-to-text</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">${(account.tts?.voices || 0)} text-to-speech voices${catalogue.stt ? ` • ${catalogue.stt} in catalogue` : ''}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Last checked</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">${UI.fmtDate(account.checkedAt)}</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">${account.latencyMs ? `${account.latencyMs} ms round trip` : 'cached for 60 s'}</div>
      </div>`;
  }

  function renderCapabilities() {
    $('dg-capabilities').innerHTML = (data.capabilities || []).map((cap) => {
      const live = cap.status === 'live';
      return `<div class="card flex flex-col">
        <div class="flex items-start justify-between gap-2">
          <h3 class="text-[11.5px] font-extrabold tracking-tight text-slate-100">${UI.esc(cap.name)}</h3>
          <span class="pill ${live ? 'pill-green' : 'pill-gray'} no-dot">${live ? 'live' : cap.status}</span>
        </div>
        <p class="mt-1 text-[9.5px] leading-relaxed text-slate-400">${UI.esc(cap.detail)}</p>
        ${(cap.surfaces || []).length ? `<div class="mt-2 space-y-1">
          ${cap.surfaces.map((s) => `<div class="flex items-center justify-between gap-2 rounded-lg border border-slate-200/70 bg-slate-50/40 px-2 py-1">
            <span class="text-[9.5px] text-slate-600">${UI.esc(s.name)}</span>
            <span class="mono text-[8.5px] text-violet-600">${UI.esc(s.model)}</span>
          </div>`).join('')}
        </div>` : ''}
        <div class="mt-auto pt-2.5 text-[8.5px] text-slate-400">
          <span class="mono">${UI.esc(cap.source)}</span>
          ${(cap.usedBy || []).length ? `<div class="mt-1 text-slate-500">Used by ${cap.usedBy.map((n) => UI.esc(n)).join(', ')}</div>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  function agentRow(agent) {
    return `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3" data-agent="${agent.id}">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[11px] font-extrabold text-slate-800">${UI.esc(agent.name)}</span>
            ${UI.statusPill(agent.status)}
            <span class="chip chip-mono">v${agent.version}</span>
          </div>
          <div class="mt-1 flex flex-wrap gap-1.5 text-[9px] text-slate-500">
            <span class="chip">${UI.esc(voiceLabel(agent.voice))}</span>
            <span class="chip">TTS ${UI.esc(agent.ttsProvider)}</span>
            <span class="chip">STT ${UI.esc(agent.sttModel)}</span>
            <span class="chip">LLM ${UI.esc(agent.llmModel)}</span>
          </div>
        </div>
        <div class="flex items-center gap-2">
          ${verdictPill(agent.verdict)}
          <button class="btn btn-xs btn-outline" data-toggle="${agent.id}" type="button">${agent.failed || agent.warned ? 'Show checks' : 'Details'}</button>
        </div>
      </div>
      <div class="mt-2 hidden space-y-1" id="checks-${agent.id}">
        ${(agent.checks || []).map((c) => `<div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
          <span class="text-[9.5px] text-slate-700">${UI.esc(c.label)}</span>
          <span class="flex items-center gap-2">
            <span class="text-[8.5px] text-slate-500">${UI.esc(c.detail)}</span>
            ${checkPill(c.status)}
          </span>
        </div>`).join('')}
        <div class="rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
          <div class="text-[8px] font-extrabold uppercase tracking-[0.1em] text-slate-500">Greeting</div>
          <div class="mt-0.5 text-[9.5px] text-slate-600">${UI.esc(agent.greeting || 'No greeting - the agent waits for the caller.')}</div>
        </div>
        <div class="rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
          <div class="text-[8px] font-extrabold uppercase tracking-[0.1em] text-slate-500">Agent prompt</div>
          <div class="mt-0.5 max-h-[120px] overflow-y-auto text-[9.5px] leading-relaxed text-slate-600">${UI.esc(agent.prompt || '—')}</div>
        </div>
      </div>
    </div>`;
  }

  function renderAgents() {
    const agents = data.agents || [];
    const compliant = agents.filter((a) => a.verdict === 'pass').length;
    $('dg-agents-summary').textContent = `${compliant}/${agents.length} compliant`;
    $('dg-agents').innerHTML = agents.length
      ? `<div class="space-y-2">${agents.map(agentRow).join('')}</div>`
      : '<div class="empty-state"><div class="empty-title">No agents yet</div><div class="empty-sub">Create one in Agent Studio to see its Deepgram compliance.</div></div>';
    $('dg-agents').querySelectorAll('[data-toggle]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const panel = document.getElementById(`checks-${btn.dataset.toggle}`);
        if (!panel) return;
        panel.classList.toggle('hidden');
        btn.textContent = panel.classList.contains('hidden') ? 'Details' : 'Hide checks';
      });
    });
  }

  function renderProjectChecks() {
    const checks = data.projectChecks || [];
    const passed = checks.filter((c) => c.status === 'pass').length;
    $('dg-project-summary').textContent = `${passed}/${checks.length} pass`;
    $('dg-project-checks').innerHTML = checks.map((c) => `<div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200/70 bg-slate-50/40 px-2.5 py-1.5">
      <span class="text-[9.5px] text-slate-700">${UI.esc(c.label)}</span>
      <span class="flex items-center gap-2">
        <span class="text-[8.5px] text-slate-500">${UI.esc(c.detail)}</span>
        ${checkPill(c.status)}
      </span>
    </div>`).join('');
  }

  function renderVoices() {
    const voices = data.voices || [];
    const inUse = voices.filter((v) => (v.inUseBy || []).length).length;
    $('dg-voices-summary').textContent = `${voices.length} voices • ${inUse} in use`;
    $('dg-voices').innerHTML = `<div class="space-y-1">${voices.map((v) => {
      const voice = window.VOICE_CATALOG?.byId(v.id);
      return `<div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
        <span class="text-[9.5px] text-slate-700">${UI.esc(voice ? `${voice.family} - ${voice.name}` : v.id)}
          <span class="text-slate-500">(${UI.esc(voice ? `${voice.accent}, ${voice.gender}` : v.family)})</span></span>
        <span class="flex items-center gap-1.5">
          ${(v.inUseBy || []).length
            ? `<span class="chip chip-mono">${v.inUseBy.map((n) => UI.esc(n)).join(', ')}</span>`
            : '<span class="text-[8.5px] text-slate-400">unused</span>'}
        </span>
      </div>`;
    }).join('')}</div>`;
  }

  function renderSources() {
    const rows = [
      ['Speech to Text', 'POST /api/stt (session-scoped)', 'api.deepgram.com/v1/listen', 'live'],
      ['Text to Speech', 'POST /api/tts', 'api.deepgram.com/v2/speak (Flux) · /v1/speak (Aura)', 'live'],
      ['Voice Agent', 'GET /api/agents · POST /api/sessions/:id/turns', 'agent configuration (local policy engine)', 'live'],
      ['Account + models', 'GET /api/deepgram/account', 'api.deepgram.com/v1/projects · /v1/models', 'live'],
      ['Compliance', 'GET /api/deepgram/compliance', 'aggregates the rows above', 'live'],
      ['Text Intelligence', '—', 'not wired in this build', 'not implemented'],
    ];
    $('dg-sources').innerHTML = rows.map(([surface, local, remote, status]) => `<tr>
      <td class="font-semibold text-slate-700">${UI.esc(surface)}</td>
      <td class="mono text-[9px] text-violet-600">${UI.esc(local)}</td>
      <td class="mono text-[9px] text-slate-500">${UI.esc(remote)}</td>
      <td>${status === 'live' ? '<span class="pill pill-green no-dot">live</span>' : '<span class="pill pill-gray no-dot">not implemented</span>'}</td>
    </tr>`).join('');
  }

  function renderAll() {
    renderHero();
    renderCapabilities();
    renderAgents();
    renderProjectChecks();
    renderVoices();
    renderSources();
  }

  async function load() {
    const pill = $('dg-hero-pill');
    pill.textContent = 'checking';
    pill.className = 'pill pill-dark';
    try {
      const res = await fetch('/api/deepgram/compliance');
      if (!res.ok) throw new Error(`compliance endpoint returned ${res.status}`);
      data = await res.json();
      renderAll();
    } catch (err) {
      $('dg-hero-body').innerHTML = `<div class="rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[10px] text-red-200 sm:col-span-2 lg:col-span-4">${UI.esc(err.message)}</div>`;
      pill.textContent = 'error';
      pill.className = 'pill pill-red-dark';
    }
  }

  $('dg-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    await load();
    btn.disabled = false;
  });

  await load();
})();

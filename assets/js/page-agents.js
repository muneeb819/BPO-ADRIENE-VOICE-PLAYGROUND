/* Agent Studio */
'use strict';

(async function initAgents() {
  await Shell.mount('agents');

  const $ = (id) => document.getElementById(id);
  const form = $('agent-form');
  const listEl = $('agent-list');

  const DEFAULTS = {
    name: '',
    campaign: 'Q1 Lead Qualification',
    description: '',
    purpose: '',
    instructions: 'You are Adriene, a professional BPO voice assistant. Be concise, empathetic, and follow deterministic rules before LLM generation. Never override transfer or eligibility policies. Ask required questions in order.',
    rules: 'Ask account-holder check, then ZIP, then prior coverage. Validate consent before transfer. Retry once on unclear input. Terminate gracefully.',
    language: 'en-US',
    voice: 'aura-asteria-en',
    tone: 'professional',
    rate: 100,
    stt: 'deepgram',
    llm: 'local',
    tts: 'deepgram-tts',
    model: 'deterministic-rules',
    temp: 0,
    transferEnabled: true,
    transferConsent: true,
    tools: 'eligibility_check, schedule_callback',
    safety: 'No hacking, no disallowed content. Follow BPO compliance. Never claim an action succeeded unless the backend confirms it.',
    maxTurns: 20,
    silence: 8,
    status: 'draft',
  };

  let agents = [];
  let editingId = null;
  let filterStatus = 'all';
  let search = '';
  const versionsCache = new Map();
  const expandedVersions = new Set();
  const loadingVersions = new Set();

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '02 — Agent Studio',
    title: 'Agent Studio',
    sub: 'Create, view, edit, duplicate, archive and delete agents. Every save is versioned and rollback-safe; provider secrets never enter the browser.',
    right: `<button class="btn btn-primary" id="new-agent-top" type="button">${Shell.icon('plus')} New agent</button>
      <a href="/testing" class="btn btn-outline">${Shell.icon('clipboard')} Regression</a>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });
  $('refresh-agents').innerHTML = Shell.icon('refresh', 'w-3.5 h-3.5');

  // ---- form helpers ------------------------------------------------------

  function setRateLabel() {
    $('rate-value').textContent = `${$('f-rate').value}%`;
  }

  function showMessage(text, type = 'error') {
    const el = $('form-message');
    if (!text) {
      el.classList.add('hidden');
      el.textContent = '';
      return;
    }
    el.className = `mt-3 rounded-lg border px-3 py-2 text-[10.5px] ${type === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : 'border-red-200 bg-red-50 text-red-700'}`;
    el.textContent = text;
  }

  function fillForm(a) {
    $('f-name').value = a.name || '';
    $('f-campaign').value = a.campaign || '';
    $('f-description').value = a.description || '';
    $('f-purpose').value = a.purpose || '';
    $('f-instructions').value = a.instructions || a.systemInstructions || '';
    $('f-rules').value = a.rules || a.conversationRules || '';
    $('f-language').value = a.language || 'en-US';
    $('f-voice').value = a.voice || 'aura-asteria-en';
    $('f-tone').value = a.tone || 'professional';
    $('f-rate').value = a.rate ?? a.speakingRate ?? 100;
    $('f-stt').value = a.stt || a.sttProvider || 'browser';
    $('f-llm').value = a.llm || a.llmProvider || 'local';
    $('f-tts').value = a.tts || a.ttsProvider || 'browser-tts';
    const llmConfig = a.llmConfig || {};
    $('f-model').value = a.model || llmConfig.model || 'deterministic-rules';
    $('f-temp').value = a.temp ?? llmConfig.temperature ?? 0;
    $('f-transfer-enabled').checked = (a.transferPolicy ? a.transferPolicy.enabled : a.transferEnabled) !== false;
    $('f-transfer-consent').checked = (a.transferPolicy ? a.transferPolicy.requireConsent : a.transferConsent) !== false;
    const tools = a.tools ?? a.enabledTools ?? [];
    $('f-tools').value = Array.isArray(tools) ? tools.join(', ') : String(tools || '');
    $('f-safety').value = a.safety ?? a.safetyRestrictions ?? '';
    const timeout = a.timeoutSettings || {};
    $('f-max-turns').value = a.maxTurns ?? timeout.maxTurns ?? 20;
    $('f-silence').value = a.silence ?? timeout.silenceTimeoutSec ?? 8;
    $('f-status').value = a.status || 'draft';
    setRateLabel();
  }

  function resetForm() {
    editingId = null;
    form.reset();
    fillForm({ ...DEFAULTS });
    $('form-title').textContent = 'New Agent Profile';
    $('form-badge').textContent = 'Draft state';
    $('form-badge').className = 'pill pill-violet';
    $('submit-btn').textContent = 'Create agent';
    $('cancel-btn').classList.add('hidden');
    showMessage('');
  }

  function readForm() {
    return {
      name: $('f-name').value.trim(),
      campaign: $('f-campaign').value.trim(),
      description: $('f-description').value.trim(),
      purpose: $('f-purpose').value.trim(),
      systemInstructions: $('f-instructions').value.trim(),
      conversationRules: $('f-rules').value.trim(),
      language: $('f-language').value,
      voice: $('f-voice').value,
      tone: $('f-tone').value,
      speakingRate: Number($('f-rate').value),
      sttProvider: $('f-stt').value,
      llmProvider: $('f-llm').value,
      ttsProvider: $('f-tts').value,
      llmConfig: {
        model: $('f-model').value.trim() || 'deterministic-rules',
        temperature: Number($('f-temp').value || 0),
      },
      transferPolicy: {
        enabled: $('f-transfer-enabled').checked,
        requireConsent: $('f-transfer-consent').checked,
      },
      enabledTools: $('f-tools').value.split(',').map((t) => t.trim()).filter(Boolean),
      safetyRestrictions: $('f-safety').value.trim(),
      timeoutSettings: {
        maxTurns: Number($('f-max-turns').value),
        silenceTimeoutSec: Number($('f-silence').value),
      },
      status: $('f-status').value,
    };
  }

  function validate(data) {
    if (data.name.length < 2) return 'Name must be at least 2 characters.';
    if (data.systemInstructions.length < 10) return 'System instructions must be at least 10 characters.';
    if (!Number.isFinite(data.speakingRate) || data.speakingRate < 50 || data.speakingRate > 200) return 'Speaking rate must be between 50 and 200.';
    if (!Number.isFinite(data.timeoutSettings.maxTurns) || data.timeoutSettings.maxTurns < 1 || data.timeoutSettings.maxTurns > 100) return 'Max turns must be between 1 and 100.';
    if (!Number.isFinite(data.timeoutSettings.silenceTimeoutSec) || data.timeoutSettings.silenceTimeoutSec < 1 || data.timeoutSettings.silenceTimeoutSec > 60) return 'Silence timeout must be between 1 and 60 seconds.';
    return '';
  }

  // ---- list rendering ----------------------------------------------------

  function versionPanel(a) {
    if (loadingVersions.has(a.id)) {
      return `<div class="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2 text-[9.5px] text-slate-400">Loading version history…</div>`;
    }
    const list = versionsCache.get(a.id);
    if (!list) return '';
    return `<div class="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-2 fade-in">
      <div class="flex items-center justify-between">
        <span class="label mb-0">Version history</span>
        <span class="text-[8.5px] text-slate-400">${list.length} snapshot${list.length === 1 ? '' : 's'}</span>
      </div>
      <div class="mt-1.5 space-y-1">
        ${list.map((v) => `<div class="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1.5">
          <span class="chip chip-mono">v${v.version}</span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[9px] font-medium text-slate-600">${UI.esc(v.changeNote || 'Snapshot')}</div>
            <div class="text-[8px] text-slate-400">${UI.fmtDate(v.createdAt)}</div>
          </div>
          ${v.version === a.version
            ? '<span class="pill pill-green no-dot">current</span>'
            : `<button class="btn btn-xs btn-outline" data-action="rollback" data-id="${a.id}" data-version="${v.version}">Rollback</button>`}
        </div>`).join('')}
      </div>
    </div>`;
  }

  function agentCard(a) {
    const expanded = expandedVersions.has(a.id);
    const archived = a.status === 'archived';
    return `<div class="agent-card" data-agent="${a.id}">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="truncate text-[12px] font-extrabold tracking-tight text-slate-900" title="${UI.attr(a.name)}">${UI.esc(a.name)}</div>
          <div class="mt-1 flex flex-wrap items-center gap-1.5">
            ${UI.statusPill(a.status)}
            <span class="chip chip-mono">v${a.version}</span>
          </div>
        </div>
        <a class="icon-btn" href="/playground?agentId=${encodeURIComponent(a.id)}" title="Open in Voice Playground" aria-label="Open in Voice Playground">${Shell.icon('play')}</a>
      </div>
      <p class="mt-2 line-clamp-2 text-[10px] leading-relaxed text-slate-500">${UI.esc(a.description || a.purpose || 'No description yet.')}</p>
      <div class="mt-2 flex flex-wrap gap-1">
        ${a.campaign ? `<span class="chip">${UI.esc(a.campaign)}</span>` : ''}
        <span class="chip">${UI.esc(a.language)} • ${UI.esc(a.voice)}</span>
        <span class="chip">${UI.esc(a.tone)}</span>
      </div>
      <div class="mt-2 truncate font-mono text-[8.5px] text-slate-400" title="Provider routing">
        ${UI.esc(a.sttProvider)} → ${UI.esc(a.llmProvider)} → ${UI.esc(a.ttsProvider)}
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-1 border-t border-slate-100 pt-2">
        <button class="btn btn-xs btn-soft" data-action="edit" data-id="${a.id}">${Shell.icon('edit')} Edit</button>
        <button class="btn btn-xs btn-outline" data-action="versions" data-id="${a.id}">${Shell.icon('history')} History</button>
        <div class="ml-auto flex items-center gap-1">
          <button class="icon-btn" data-action="duplicate" data-id="${a.id}" title="Duplicate agent" aria-label="Duplicate agent">${Shell.icon('copy')}</button>
          <button class="icon-btn" data-action="archive" data-id="${a.id}" title="${archived ? 'Restore agent' : 'Archive agent'}" aria-label="${archived ? 'Restore agent' : 'Archive agent'}">${Shell.icon(archived ? 'refresh' : 'archive')}</button>
          <button class="icon-btn danger" data-action="delete" data-id="${a.id}" title="Delete agent" aria-label="Delete agent">${Shell.icon('trash')}</button>
        </div>
      </div>
      <div class="mt-1 text-[8px] text-slate-400">Updated ${UI.timeAgo(a.updatedAt)} • ${UI.fmtDate(a.updatedAt)}</div>
      ${expanded ? versionPanel(a) : ''}
    </div>`;
  }

  function renderAgents() {
    const filtered = agents.filter((a) => {
      if (filterStatus !== 'all' && a.status !== filterStatus) return false;
      if (search) {
        const hay = `${a.name} ${a.campaign} ${a.description}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
    const counts = ['draft', 'testing', 'approved', 'archived'].map((s) => agents.filter((a) => a.status === s).length);
    $('agent-count').textContent = `${agents.length} agent${agents.length === 1 ? '' : 's'} • SQLite persisted`;
    $('agent-count').title = `Draft ${counts[0]} • Testing ${counts[1]} • Approved ${counts[2]} • Archived ${counts[3]}`;

    if (!filtered.length) {
      listEl.innerHTML = agents.length
        ? UI.emptyState('No matching agents', 'Try a different status filter or search term.', 'search')
        : UI.emptyState('No agents yet', 'Create a profile on the left — it is saved to SQLite immediately.', 'layers');
      return;
    }
    listEl.innerHTML = filtered.map(agentCard).join('');
  }

  async function loadAgents() {
    try {
      agents = await API.agents();
      renderAgents();
    } catch (err) {
      listEl.innerHTML = `<div class="rounded-lg border border-red-200 bg-red-50 p-3 text-[10px] text-red-700">Could not load agents: ${UI.esc(err.message)}</div>`;
      $('agent-count').textContent = 'API unavailable';
    }
  }

  // ---- actions -----------------------------------------------------------

  function populateForEdit(a) {
    editingId = a.id;
    fillForm(a);
    $('form-title').textContent = 'Edit Agent Profile';
    $('form-badge').textContent = `${a.status} • v${a.version}`;
    $('form-badge').className = `pill pill-${({ draft: 'gray', testing: 'amber', approved: 'green', archived: 'gray' }[a.status] || 'violet')}`;
    $('submit-btn').textContent = 'Save changes';
    $('cancel-btn').classList.remove('hidden');
    showMessage('');
    $('agent-form-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function toggleVersions(id) {
    if (expandedVersions.has(id)) {
      expandedVersions.delete(id);
      renderAgents();
      return;
    }
    expandedVersions.add(id);
    loadingVersions.add(id);
    renderAgents();
    try {
      versionsCache.set(id, await API.versions(id));
    } catch (err) {
      UI.toast(err.message, 'error');
      expandedVersions.delete(id);
    } finally {
      loadingVersions.delete(id);
      renderAgents();
    }
  }

  listEl.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const agent = agents.find((a) => a.id === id);
    if (!agent && action !== 'rollback') return;

    if (action === 'edit') {
      populateForEdit(agent);
      return;
    }
    if (action === 'versions') {
      await toggleVersions(id);
      return;
    }
    if (action === 'duplicate') {
      btn.disabled = true;
      try {
        const copy = await API.duplicateAgent(id);
        UI.toast(`Duplicated as "${copy.name}"`, 'success');
        await loadAgents();
      } catch (err) {
        UI.toast(err.message, 'error');
      } finally {
        btn.disabled = false;
      }
      return;
    }
    if (action === 'archive') {
      const restore = agent.status === 'archived';
      btn.disabled = true;
      try {
        await API.updateAgent(id, { status: restore ? 'draft' : 'archived' });
        UI.toast(restore ? 'Agent restored to draft' : 'Agent archived', 'success');
        await loadAgents();
      } catch (err) {
        UI.toast(err.message, 'error');
      } finally {
        btn.disabled = false;
      }
      return;
    }
    if (action === 'delete') {
      if (!window.confirm(`Delete "${agent.name}"?\n\nThis also deletes its versions, sessions and test cases. This cannot be undone.`)) return;
      btn.disabled = true;
      try {
        await API.deleteAgent(id);
        if (editingId === id) resetForm();
        versionsCache.delete(id);
        expandedVersions.delete(id);
        UI.toast('Agent deleted', 'success');
        await loadAgents();
      } catch (err) {
        UI.toast(err.message, 'error');
        btn.disabled = false;
      }
      return;
    }
    if (action === 'rollback') {
      const version = Number(btn.dataset.version);
      if (!window.confirm(`Roll back to v${version}?\n\nThe current configuration is preserved in history; a new version will be created.`)) return;
      btn.disabled = true;
      try {
        const updated = await API.rollbackAgent(id, version);
        versionsCache.set(id, await API.versions(id));
        expandedVersions.add(id);
        UI.toast(`Rolled back to v${version} (now v${updated.version})`, 'success');
        await loadAgents();
        if (editingId === id) populateForEdit(updated);
      } catch (err) {
        UI.toast(err.message, 'error');
        btn.disabled = false;
      }
    }
  });

  // ---- form events -------------------------------------------------------

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = readForm();
    const problem = validate(data);
    if (problem) {
      showMessage(problem, 'error');
      UI.toast(problem, 'error');
      return;
    }
    const btn = $('submit-btn');
    const original = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg> Saving…`;
    try {
      if (editingId) {
        const updated = await API.updateAgent(editingId, data);
        UI.toast(`Saved "${updated.name}" as v${updated.version}`, 'success');
        versionsCache.delete(editingId);
      } else {
        const created = await API.createAgent(data);
        UI.toast(`Agent "${created.name}" created`, 'success');
      }
      resetForm();
      await loadAgents();
    } catch (err) {
      showMessage(err.message, 'error');
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = editingId ? 'Save changes' : 'Create agent';
    }
  });

  $('cancel-btn').addEventListener('click', resetForm);
  $('reset-btn').addEventListener('click', resetForm);
  $('new-agent-side').addEventListener('click', () => { resetForm(); $('f-name').focus(); $('agent-form-card').scrollIntoView({ behavior: 'smooth' }); });
  $('new-agent-top').addEventListener('click', () => { resetForm(); $('f-name').focus(); $('agent-form-card').scrollIntoView({ behavior: 'smooth' }); });
  $('refresh-agents').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg>`;
    await loadAgents();
    btn.disabled = false;
    btn.innerHTML = Shell.icon('refresh', 'w-3.5 h-3.5');
  });

  $('f-rate').addEventListener('input', setRateLabel);
  $('status-filter').addEventListener('change', (event) => { filterStatus = event.target.value; renderAgents(); });
  $('search-agents').addEventListener('input', UI.debounce((event) => { search = event.target.value.trim().toLowerCase(); renderAgents(); }, 150));

  resetForm();
  await loadAgents();
})();

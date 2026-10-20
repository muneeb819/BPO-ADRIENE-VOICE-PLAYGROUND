/* Scenario Testing & Evaluation */
'use strict';

(async function initTesting() {
  await Shell.mount('testing');

  const $ = (id) => document.getElementById(id);
  const SCRIPT_TEMPLATE = `[
  { "role": "user", "content": "hello" },
  { "role": "user", "content": "what is price?" }
]`;

  let agents = [];
  let agent = null;
  let cases = [];
  let runs = [];
  let selected = new Set();
  let currentRunId = null;

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '06 — Scenario Testing & Evaluation',
    title: 'Scenario Testing',
    sub: 'Reusable cases • Deterministic regression suites • Pass/fail with transcripts, timings and rule violations • JSON/CSV export.',
    right: `<span class="pill pill-violet no-dot">Deterministic</span>
      <span class="pill pill-ghost no-dot">9 fixture patterns</span>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  // ---- messages ----------------------------------------------------------

  function showCaseMessage(text, type = 'error') {
    const el = $('case-form-message');
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

  // ---- cases -------------------------------------------------------------

  function categoryPill(category) {
    return UI.statusPill(category);
  }

  function caseRow(c) {
    const checked = selected.has(c.id);
    const script = JSON.stringify(c.script || []).replace(/","/g, '", "');
    return `<label class="case-row block cursor-pointer ${checked ? 'selected' : ''}">
      <div class="flex items-start gap-2">
        <input class="checkbox mt-0.5" type="checkbox" data-case-id="${c.id}" ${checked ? 'checked' : ''} />
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="text-[11px] font-bold tracking-tight text-slate-800">${UI.esc(c.name)}</span>
            ${categoryPill(c.category)}
          </div>
          <div class="mt-0.5 text-[8.5px] text-slate-400">
            Intent: ${UI.esc(c.expectedIntent || 'any')} • Questions: ${UI.esc((c.requiredQuestions || []).join(', ') || 'none')} • ${UI.fmtDateShort(c.createdAt)}
          </div>
          <pre class="mt-1.5 max-h-[54px] overflow-hidden whitespace-pre-wrap break-all rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[8px] leading-relaxed text-slate-500">${UI.esc(script)}</pre>
        </div>
      </div>
    </label>`;
  }

  function updateSelection() {
    const pill = $('selection-pill');
    pill.textContent = selected.size ? `${selected.size} selected` : `All ${cases.length} will run`;
    $('run-btn').disabled = !cases.length;
    $('select-all').disabled = !cases.length;
    $('clear-all').disabled = !selected.size;
    const all = $('case-list').querySelectorAll('[data-case-id]');
    all.forEach((box) => {
      box.closest('.case-row')?.classList.toggle('selected', box.checked);
    });
  }

  function renderCases() {
    $('case-count').textContent = String(cases.length);
    $('case-updated').textContent = cases.length ? `Latest ${UI.timeAgo(cases[0].createdAt)}` : '—';
    if (!cases.length) {
      $('case-list').innerHTML = `<div class="empty-state">
        <div class="empty-icon">${Shell.icon('clipboard')}</div>
        <div class="empty-title">No test cases for this agent</div>
        <div class="empty-sub">Use “Seed Fixtures” to create the 9-pattern regression suite, or write a case on the left.</div>
      </div>`;
    } else {
      $('case-list').innerHTML = cases.map(caseRow).join('');
    }
    updateSelection();
  }

  // ---- runs --------------------------------------------------------------

  function timingLabel(result) {
    const t = result.timings || {};
    const parts = [`e2e ${t.e2e ?? '—'} ms`];
    if (t.stt) parts.push(`STT ${t.stt} ms`);
    if (t.llm && t.llm !== t.e2e) parts.push(`LLM ${t.llm} ms`);
    if (t.tts) parts.push(`TTS ${t.tts} ms`);
    return parts.join(' · ');
  }

  function transcriptHTML(results) {
    const turns = results.transcript || [];
    if (!turns.length) return '<div class="text-[9px] text-slate-400">No transcript captured.</div>';
    return turns.map((t) => `<div class="flex items-start gap-1.5">
      <span class="mt-0.5 flex h-4 w-4 flex-none items-center justify-center rounded ${t.role === 'user' ? 'bg-slate-100 text-slate-500' : 'bg-violet-100 text-violet-700'} text-[7px] font-extrabold">${t.role === 'user' ? 'U' : 'A'}</span>
      <div class="min-w-0 flex-1">
        <div class="text-[9px] leading-relaxed text-slate-600">${UI.esc(t.content)}</div>
        ${t.latencyMs ? `<div class="text-[7.5px] text-slate-400">${t.latencyMs} ms</div>` : ''}
      </div>
    </div>`).join('');
  }

  function resultRow(result) {
    const pass = result.status === 'pass';
    const errors = result.errors || [];
    const violations = result.ruleViolations || [];
    return `<details class="result-details overflow-hidden rounded-xl border ${pass ? 'border-emerald-200' : 'border-red-200'}">
      <summary class="flex flex-wrap items-center gap-2 bg-${pass ? 'emerald' : 'red'}-50 px-3 py-2.5">
        <span class="text-[9px] font-extrabold ${pass ? 'text-emerald-700' : 'text-red-700'}">${pass ? 'PASS' : 'FAIL'}</span>
        <span class="text-[11px] font-bold tracking-tight text-slate-800">${UI.esc(result.caseName)}</span>
        ${categoryPill(result.category)}
        <span class="ml-auto font-mono text-[8.5px] text-slate-500">${UI.esc(timingLabel(result))}</span>
        <span class="text-[8px] text-slate-400">${pass ? 'Transcript' : 'Errors + transcript'}</span>
      </summary>
      <div class="bg-white px-3 py-2.5">
        ${errors.length ? `<div class="rounded-lg border border-red-200 bg-red-50 px-2 py-1.5 text-[9px] leading-relaxed text-red-700">
          ${errors.map((e) => `<div>• ${UI.esc(e)}</div>`).join('')}
        </div>` : ''}
        ${violations.length ? `<div class="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-[9px] leading-relaxed text-amber-800">
          ${violations.map((e) => `<div>• Rule violation: ${UI.esc(e)}</div>`).join('')}
        </div>` : ''}
        <div class="mt-1.5 flex flex-wrap gap-1 text-[8px] text-slate-500">
          <span class="chip chip-mono">detected: ${UI.esc((result.detectedIntents || []).join(' → ') || 'none')}</span>
          <span class="chip chip-mono">ended: ${result.sessionState?.ended ? 'yes' : 'no'}</span>
          <span class="chip chip-mono">consent: ${result.sessionState?.consent ? 'yes' : 'no'}</span>
          <span class="chip chip-mono">barge-ins: ${result.sessionState?.bargeIns ?? 0}</span>
        </div>
        <div class="mt-2 space-y-1.5 border-t border-slate-100 pt-2">${transcriptHTML(result)}</div>
      </div>
    </details>`;
  }

  function renderRunOptions() {
    const select = $('run-history');
    if (!runs.length) {
      select.innerHTML = '<option value="">No runs</option>';
      select.disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = runs.map((r) => `<option value="${r.id}">${UI.esc(r.suiteName)} — ${r.status} (${r.passed}/${r.totalCases})</option>`).join('');
    select.value = currentRunId || runs[0].id;
  }

  function renderRun() {
    $('run-count').textContent = String(runs.length);
    const run = runs.find((r) => r.id === currentRunId) || runs[0] || null;
    renderRunOptions();
    if (!run) {
      $('export-json').classList.add('hidden');
      $('export-csv').classList.add('hidden');
      $('run-summary').innerHTML = `<div class="empty-state">
        <div class="empty-icon">${Shell.icon('chart')}</div>
        <div class="empty-title">No regression runs yet</div>
        <div class="empty-sub">Seed fixtures and run the suite to see pass/fail evidence.</div>
      </div>`;
      $('run-results').innerHTML = '';
      return;
    }
    currentRunId = run.id;
    renderRunOptions();
    $('export-json').classList.remove('hidden');
    $('export-csv').classList.remove('hidden');
    const snapshot = run.configSnapshot || {};
    $('run-summary').innerHTML = `<div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="text-[12px] font-extrabold tracking-tight text-slate-900">${UI.esc(run.suiteName)}</div>
        ${UI.statusPill(run.status)}
        <span class="text-[9px] text-slate-400">${UI.fmtDate(run.createdAt)}</span>
        <div class="ml-auto flex flex-wrap items-center gap-2 text-[9px] font-semibold">
          <span class="text-slate-500">${run.totalCases} cases</span>
          <span class="text-emerald-600">${run.passed} passed</span>
          <span class="text-red-600">${run.failed} failed</span>
        </div>
      </div>
      <div class="mt-2 flex flex-wrap gap-1">
        <span class="chip chip-mono">agent: ${UI.esc(snapshot.name || agent?.name || 'unknown')} v${snapshot.version || '—'}</span>
        <span class="chip chip-mono">${UI.esc(snapshot.sttProvider || '—')} → ${UI.esc(snapshot.llmProvider || '—')} → ${UI.esc(snapshot.ttsProvider || '—')}</span>
        <span class="chip chip-mono">max turns: ${snapshot.timeoutSettings?.maxTurns ?? '—'}</span>
        <span class="chip chip-mono">run: ${UI.shortId(run.id)}</span>
      </div>
    </div>`;
    $('run-results').innerHTML = (run.results || []).map(resultRow).join('');
  }

  // ---- data load ---------------------------------------------------------

  async function loadRuns() {
    if (!agent) return;
    runs = await API.testRuns(`?agentId=${encodeURIComponent(agent.id)}`);
    if (!runs.find((r) => r.id === currentRunId)) currentRunId = runs[0]?.id || null;
    renderRun();
  }

  async function loadCases() {
    if (!agent) return;
    cases = await API.testCases(`?agentId=${encodeURIComponent(agent.id)}`);
    selected.clear();
    renderCases();
  }

  async function loadForAgent() {
    if (!agent) return;
    $('case-list').innerHTML = '<div class="py-8 text-center text-[10px] text-slate-400">Loading cases…</div>';
    try {
      await Promise.all([loadCases(), loadRuns()]);
    } catch (err) {
      UI.toast(err.message, 'error');
      $('case-list').innerHTML = `<div class="rounded-lg border border-red-200 bg-red-50 p-3 text-[10px] text-red-700">${UI.esc(err.message)}</div>`;
    }
  }

  async function loadAgents() {
    try {
      agents = await API.agents();
    } catch (err) {
      agents = [];
      UI.toast(err.message, 'error');
    }
    const select = $('test-agent');
    if (!agents.length) {
      select.innerHTML = '<option value="">No agents — create one first</option>';
      select.disabled = true;
      $('seed-btn').disabled = true;
      $('run-btn').disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = agents.map((a) => `<option value="${a.id}">${UI.esc(a.name)} • v${a.version}${a.status === 'archived' ? ' (archived)' : ''}</option>`).join('');
    const wanted = UI.getParam('agentId');
    agent = agents.find((a) => a.id === wanted) || agents.find((a) => a.status !== 'archived') || agents[0];
    select.value = agent.id;
    await loadForAgent();
  }

  // ---- events ------------------------------------------------------------

  $('test-agent').addEventListener('change', async (event) => {
    agent = agents.find((a) => a.id === event.target.value) || null;
    currentRunId = null;
    await loadForAgent();
  });

  $('case-list').addEventListener('change', (event) => {
    const box = event.target.closest('[data-case-id]');
    if (!box) return;
    if (box.checked) selected.add(box.dataset.caseId);
    else selected.delete(box.dataset.caseId);
    updateSelection();
  });

  $('select-all').addEventListener('click', () => {
    selected = new Set(cases.map((c) => c.id));
    renderCases();
  });

  $('clear-all').addEventListener('click', () => {
    selected.clear();
    renderCases();
  });

  $('seed-btn').addEventListener('click', async (event) => {
    if (!agent) return;
    const btn = event.currentTarget;
    UI.setBusy(btn, true, 'Seeding');
    try {
      const result = await API.seedFixtures(agent.id);
      UI.toast(result.created
        ? `Added ${result.created} fixtures (${result.total} total patterns)`
        : `Fixtures already present (${result.total} patterns)`, 'success');
      await loadCases();
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  $('run-btn').addEventListener('click', async (event) => {
    if (!agent) return;
    if (!cases.length) {
      UI.toast('No test cases to run. Seed fixtures first.', 'error');
      return;
    }
    const btn = event.currentTarget;
    UI.setBusy(btn, true, 'Running');
    try {
      const payload = { agentId: agent.id };
      if (selected.size) payload.caseIds = [...selected];
      const run = await API.runTests(payload);
      currentRunId = run.id;
      await loadRuns();
      renderRun();
      UI.toast(run.failed ? `${run.passed}/${run.totalCases} passed — ${run.failed} failed` : `All ${run.totalCases} cases passed`, run.failed ? 'error' : 'success');
      $('run-summary').scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  $('run-history').addEventListener('change', (event) => {
    currentRunId = event.target.value;
    renderRun();
  });

  $('case-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!agent) {
      showCaseMessage('Select an agent first.', 'error');
      return;
    }
    const name = $('case-name').value.trim();
    if (name.length < 3) {
      showCaseMessage('Case name must be at least 3 characters.', 'error');
      return;
    }
    let script;
    try {
      script = JSON.parse($('case-script').value);
    } catch {
      showCaseMessage('Script must be valid JSON.', 'error');
      return;
    }
    if (!Array.isArray(script) || !script.length) {
      showCaseMessage('Script must be a non-empty array of user steps.', 'error');
      return;
    }
    const btn = $('create-case-btn');
    btn.disabled = true;
    btn.textContent = 'Creating…';
    try {
      await API.createTestCase({
        agentId: agent.id,
        name,
        description: $('case-description').value.trim(),
        category: $('case-category').value,
        expectedIntent: $('case-intent').value || null,
        requiredQuestions: $('case-required').value.split(',').map((q) => q.trim()).filter(Boolean),
        script,
      });
      showCaseMessage('Test case created.', 'success');
      $('case-name').value = '';
      $('case-description').value = '';
      $('case-required').value = '';
      $('case-script').value = SCRIPT_TEMPLATE;
      selected.clear();
      await loadCases();
      UI.toast('Test case created', 'success');
    } catch (err) {
      showCaseMessage(err.message, 'error');
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Create Case';
    }
  });

  // ---- export ------------------------------------------------------------

  function currentRun() {
    return runs.find((r) => r.id === currentRunId) || runs[0] || null;
  }

  $('export-json').addEventListener('click', () => {
    const run = currentRun();
    if (!run) return;
    const safe = (agent?.name || 'agent').replace(/[^a-z0-9]+/gi, '-').toLowerCase();
    UI.download(`regression-${safe}-${run.id.slice(0, 8)}.json`, JSON.stringify(run, null, 2), 'application/json');
  });

  $('export-csv').addEventListener('click', () => {
    const run = currentRun();
    if (!run) return;
    const esc = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
    const rows = [['Case', 'Category', 'Status', 'Detected intents', 'E2E ms', 'Errors', 'Rule violations']];
    (run.results || []).forEach((r) => {
      rows.push([
        r.caseName,
        r.category,
        r.status,
        (r.detectedIntents || []).join(' -> '),
        r.timings?.e2e ?? '',
        (r.errors || []).join(' | '),
        (r.ruleViolations || []).join(' | '),
      ]);
    });
    const csv = rows.map((row) => row.map(esc).join(',')).join('\r\n');
    const safe = (agent?.name || 'agent').replace(/[^a-z0-9]+/gi, '-').toLowerCase();
    UI.download(`regression-${safe}-${run.id.slice(0, 8)}.csv`, csv, 'text/csv');
  });

  // ---- boot --------------------------------------------------------------

  $('case-script').value = SCRIPT_TEMPLATE;
  await loadAgents();
})();

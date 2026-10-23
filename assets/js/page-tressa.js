/* Tressa — USA Medicare training workspace */
'use strict';

(async function initTressa() {
  await Shell.mount('tressa');

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
  const fmtNum = (value) => Number(value || 0).toLocaleString();
  const fmtDate = (value) => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  };
  const pillClass = (status) => {
    const s = String(status || '').toLowerCase();
    if (s === 'active' || s === 'pass' || s === 'passed' || s === 'complete') return 'pill-green';
    if (s === 'deployed') return 'pill-violet';
    if (s === 'inactive' || s === 'fail' || s === 'failed') return 'pill-red';
    if (s === 'not_run' || s === 'not run' || s === 'not_deployed' || s === 'not deployed' || s === 'open-admin-action') return 'pill-amber';
    return 'pill-gray';
  };
  const sevClass = (sev) => ({ critical: 'pill-red', high: 'pill-amber', medium: 'pill-blue', low: 'pill-gray' }[String(sev || '').toLowerCase()] || 'pill-gray');
  const label = (value) => String(value ?? '').replace(/_/g, ' ');
  const short = (value, n = 280) => {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    return text.length > n ? text.slice(0, n - 1) + '…' : text;
  };

  let state = { training: null, agent: null, versions: [], validation: null, health: null };
  let busy = false;

  function toast(message, bad = false) {
    const el = $('toast');
    el.textContent = message;
    el.className = `fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-xl border px-4 py-2 text-[11px] font-semibold shadow-xl ${bad ? 'border-red-200 bg-red-50 text-red-700' : 'border-slate-200 bg-white text-slate-700'}`;
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(() => el.classList.add('hidden'), 4200);
  }

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: 'Nexus · USA Medicare',
    title: 'Tressa Training Workspace',
    sub: 'Review the actual source material, inspect grounded retrieval, run the source-derived validation suite, and manage campaign/compliance state without confusing configuration with deployment.',
    right: `<a class="btn btn-outline" href="/agents">${Shell.icon('layers')} Agent Studio</a>
      <a class="btn btn-primary" href="/playground">${Shell.icon('mic')} Test voice</a>`,
  });
  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-4 h-4');
  });

  async function loadAll() {
    try {
      const [training, agents, health] = await Promise.all([
        API.get('/api/training'),
        API.agents(),
        API.health(),
      ]);
      state.training = training;
      state.health = health;
      state.agent = (agents || []).find((a) => String(a.callName || '').toLowerCase() === 'tressa'
        && String(a.campaign || '').toLowerCase() === 'usa medicare')
        || (agents || []).find((a) => String(a.callName || '').toLowerCase() === 'tressa')
        || null;

      const validation = await API.get('/api/training/validation').catch(() => ({ available: false }));
      state.validation = validation && validation.available !== false && validation.summary ? validation : null;

      if (state.agent) {
        state.versions = await API.versions(state.agent.id).catch(() => []);
      } else {
        state.versions = [];
      }
      renderAll();
    } catch (err) {
      toast(err.message || 'Could not load Tressa workspace.', true);
      $('tressa-status').textContent = 'Unavailable';
      $('tressa-status').className = 'pill pill-red';
    }
  }

  function renderAll() {
    renderHero();
    renderSources();
    renderValidation();
    renderCampaign();
    renderCompliance();
    renderLifecycle();
    renderHealth();
    renderVersions();
    renderApproval();
  }

  function renderHero() {
    const t = state.training || {};
    const a = state.agent;
    const v = t.validation || {};
    const summary = v.summary || {};
    const readiness = v.readiness || {};
    $('tressa-name').textContent = a ? a.callName || 'Tressa' : 'Tressa';
    $('tressa-agent-version').textContent = a ? `v${a.version}` : 'profile missing';
    const status = a ? a.displayStatus : 'Inactive';
    $('tressa-status').textContent = status === 'Active' ? 'Active · controlled testing' : status;
    $('tressa-status').className = `pill ${pillClass(status)}`;
    $('tressa-sub').textContent = a
      ? `${a.displayName}. ${a.description || 'Training-material-grounded USA Medicare voice agent.'}`
      : 'No Tressa profile found. The knowledge base is present, but the agent is Inactive until configured.';
    $('tressa-kb-version').textContent = t.version || '—';
    $('tressa-test-count').textContent = t.tests ? t.tests.total : '—';
    $('tressa-chunk-count').textContent = fmtNum(t.chunkCount);
    $('tressa-last-validation').textContent = v.generatedAt ? `Validated ${fmtDate(v.generatedAt)}` : 'Validation not run';
    $('tressa-last-validation').className = `pill ${v.generatedAt ? 'pill-green' : 'pill-amber'} no-dot`;
    $('edit-agent-link').href = '/agents';
    $('playground-link').href = '/playground';

    const byType = summary.byType || {};
    const retrieval = byType.retrieval || { passed: 0, total: 0 };
    const compliance = byType.compliance || { passed: 0, total: 0 };
    const cards = [
      ['Retrieval', summary.total ? `${retrieval.passed}/${retrieval.total}` : '—', 'Source/slide recall'],
      ['Compliance', summary.total ? `${compliance.passed}/${compliance.total}` : '—', 'Guardrail checks'],
      ['Live voice test', readiness.liveConversationValidation === 'not_run' ? 'Not run' : (readiness.liveConversationValidation || '—'), 'No model key / deployment'],
      ['Deployment', readiness.deployment === 'not_deployed' ? 'Not deployed' : (readiness.deployment || '—'), 'Verified state only'],
    ];
    $('hero-stats').innerHTML = cards.map(([k, val, sub]) => `
      <div class="rounded-xl border border-slate-200 bg-white/70 px-3 py-2">
        <div class="text-[8.5px] font-extrabold uppercase tracking-[0.1em] text-slate-400">${esc(k)}</div>
        <div class="mt-0.5 text-[15px] font-extrabold tracking-tight text-slate-900">${esc(val)}</div>
        <div class="text-[8.5px] text-slate-400">${esc(sub)}</div>
      </div>`).join('');
  }

  function renderSources() {
    const t = state.training || {};
    const manifest = t.sourceManifest || {};
    const docs = manifest.documents || [];
    const unique = docs.filter((d) => d.kind !== 'duplicate');
    const docx = docs.filter((d) => d.kind === 'docx').length;
    $('stat-docs').textContent = fmtNum(unique.length);
    $('stat-slides').textContent = fmtNum((manifest.totalSlides || 0) + docx);
    $('stat-chars').textContent = fmtNum(manifest.totalCharacters);
    $('stat-chunks').textContent = fmtNum(t.chunkCount);

    const warnings = [];
    if ((manifest.duplicates || []).length) {
      warnings.push(`<span class="pill pill-amber no-dot">${manifest.duplicates.length} duplicate retained, excluded from index</span>`);
    }
    for (const w of manifest.warnings || []) warnings.push(`<span class="pill pill-red no-dot">${esc(w)}</span>`);
    if (!warnings.length) warnings.push('<span class="pill pill-green no-dot">No missing or duplicate source warnings</span>');
    $('source-warnings').innerHTML = warnings.join('');

    if (!docs.length) {
      $('documents-body').innerHTML = '<tr><td colspan="6" class="text-slate-400">No source documents registered.</td></tr>';
      return;
    }
    $('documents-body').innerHTML = docs.map((d) => {
      const dup = d.kind === 'duplicate';
      const type = dup ? 'Duplicate' : String(d.kind || '').toUpperCase();
      const slides = d.kind === 'docx' ? '1 DOCX' : (d.slides ?? '—');
      return `<tr>
        <td class="max-w-[360px]"><div class="truncate font-semibold text-slate-800" title="${esc(d.file)}">${esc(d.file)}</div>
          <div class="mono truncate text-[8.5px] text-slate-400">${esc(String(d.sha256 || '').slice(0, 16))}…</div></td>
        <td>${esc(type)}</td>
        <td>${esc(slides)}</td>
        <td>${fmtNum(d.characters)}</td>
        <td>${dup ? '<span class="pill pill-gray no-dot">No — duplicate</span>' : '<span class="pill pill-green no-dot">Indexed</span>'}</td>
        <td class="text-right">${d.hasExtractedText ? `<button class="btn btn-ghost btn-sm" data-doc="${esc(d.file)}" type="button">View</button>` : '<span class="text-[9px] text-slate-400">—</span>'}</td>
      </tr>`;
    }).join('');
  }

  function renderValidation() {
    const v = state.validation;
    const s = v ? v.summary || {} : {};
    const r = v ? v.readiness || {} : {};
    const byType = s.byType || {};
    const checks = [
      ['Total checks', s.total ?? '—'],
      ['Pass rate', s.total ? `${s.passRate}%` : '—'],
      ['Failures', s.failed ?? '—'],
      ['Live voice', r.liveConversationValidation === 'not_run' ? 'Not run' : (r.liveConversationValidation || '—')],
    ];
    $('validation-stats').innerHTML = checks.map(([k, val], i) => `
      <div class="rounded-xl border ${i === 2 && Number(s.failed) ? 'border-red-200 bg-red-50/50' : 'border-slate-200 bg-white/70'} px-3 py-2">
        <div class="text-[8.5px] font-extrabold uppercase tracking-[0.1em] text-slate-400">${esc(k)}</div>
        <div class="mt-0.5 text-[15px] font-extrabold tracking-tight text-slate-900">${esc(val)}</div>
      </div>`).join('');

    const controlled = r.readyForControlledTesting;
    const deployed = r.readyForDeployment;
    $('readiness-controlled').textContent = controlled ? 'Ready for controlled testing' : 'Not ready for testing';
    $('readiness-controlled').className = `pill ${controlled ? 'pill-green' : 'pill-amber'} no-dot`;
    $('readiness-deployed').textContent = deployed ? 'Deployment approved' : 'Deployment not approved';
    $('readiness-deployed').className = `pill ${deployed ? 'pill-violet' : 'pill-gray'} no-dot`;

    const typeBits = Object.entries(byType).map(([k, val]) => `${k}: ${val.passed}/${val.total}`);
    $('readiness-note').textContent = v
      ? `${typeBits.join(' · ')}. ${r.liveConversationValidation === 'not_run' ? 'Live conversational voice validation is still pending.' : ''} Passing this suite supports controlled testing only; deployment requires the remaining compliance and live-voice checks.`
      : 'No validation run recorded. The source suite has not been executed against the linked agent.';

    const failures = v ? (v.results || []).filter((x) => x.status === 'fail') : [];
    $('validation-failures').innerHTML = failures.length
      ? `<div class="rounded-xl border border-red-200 bg-red-50/60 p-3">
          <div class="text-[10px] font-extrabold text-red-800">${failures.length} failure(s) require correction</div>
          <ul class="mt-1.5 list-disc space-y-1 pl-4 text-[9.5px] leading-relaxed text-red-700">
            ${failures.slice(0, 8).map((f) => `<li><strong>${esc(f.id)}</strong> — ${esc(f.detail)}</li>`).join('')}
          </ul>
        </div>`
      : (v ? '<div class="pill pill-green no-dot">All executed checks passed</div>' : '');

    const rows = v ? (v.results || []) : [];
    $('validation-body').innerHTML = rows.length ? rows.map((x) => {
      const top = (x.top || [])[0];
      const evidence = x.detail + (top ? ` Top: ${top.source}${top.slide ? ` slide ${top.slide}` : ''} (${top.score}).` : '');
      return `<tr class="result-row ${x.status}">
        <td class="mono text-[9px]">${esc(x.id)}</td>
        <td>${esc(x.type)}</td>
        <td><span class="pill ${pillClass(x.status)} no-dot">${esc(x.status)}</span></td>
        <td class="text-[9.5px] leading-relaxed">${esc(evidence)}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4" class="text-slate-400">No validation run yet.</td></tr>';

    $('download-report-btn').disabled = !v;
    $('validation-details').open = !!v && failures.length > 0;
    $('validation-limits').innerHTML = `<strong>Honest limitation:</strong> ${esc((v && (v.limitations || [])[0]) || 'live conversational/generative voice validation is not run by this local suite. It requires a configured model key or a verified LiveKit Cloud deployment.')}`;
  }

  function renderCampaign() {
    const t = state.training || {};
    const c = t.campaign || {};
    const a = state.agent;
    const products = (c.products || []).join(', ') || '—';
    const order = (c.qualificationOrder || []).join(' → ') || '—';
    const rows = [
      ['Display label', a ? a.displayName : c.displayName || '—'],
      ['Agency on call', c.agencyName || '—'],
      ['Campaign', c.name || 'USA Medicare'],
      ['Products', products],
      ['Qualification order', order],
      ['Voice / pipeline', a ? `${a.voice} · ${a.sttProvider}/${a.ttsProvider}` : '—'],
      ['Transfer rule', c.transferRule || '—'],
      ['Age rule', c.ageRule || '—'],
      ['Carrier / TPMO disclosure', c.carrierDisclosure || '—'],
    ];
    $('campaign-body').innerHTML = rows.map(([k, val]) => `
      <div class="flex gap-2 border-b border-slate-100 pb-1.5 last:border-0 last:pb-0">
        <div class="w-[108px] flex-none text-[8.5px] font-extrabold uppercase tracking-[0.06em] text-slate-400">${esc(k)}</div>
        <div class="min-w-0 flex-1 leading-relaxed text-slate-600">${esc(val)}</div>
      </div>`).join('');
  }

  function renderCompliance() {
    const t = state.training || {};
    const c = t.compliance || {};
    const gaps = t.conflicts || [];
    const open = gaps.filter((g) => String(g.status || '').startsWith('open'));
    $('open-gap-count').textContent = `${open.length} open`;
    $('open-gap-count').className = `pill ${open.length ? 'pill-amber' : 'pill-green'} no-dot`;
    $('gap-total').textContent = gaps.length;
    $('disclosure-list').innerHTML = (c.requiredDisclosures || []).map((d) => `
      <div class="guard-item"><span class="mt-0.5 text-emerald-600">✓</span><span>${esc(d)}</span></div>`).join('')
      || '<div class="text-[10px] text-slate-400">No disclosure list loaded.</div>';
    $('gap-list').innerHTML = gaps.map((g) => `
      <div class="rounded-lg border border-slate-200 bg-white/60 p-2">
        <div class="flex items-start justify-between gap-2">
          <div class="text-[9.5px] font-bold leading-snug text-slate-700">${esc(g.title)}</div>
          <span class="pill ${sevClass(g.severity)} no-dot">${esc(g.severity)}</span>
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-1.5">
          <span class="pill ${pillClass(g.status)} no-dot">${esc(label(g.status))}</span>
          <span class="text-[8.5px] text-slate-400">${esc(g.reviewer || 'review')}</span>
        </div>
      </div>`).join('') || '<div class="text-[10px] text-slate-400">No conflicts registered.</div>';
  }

  function renderLifecycle() {
    const a = state.agent;
    const v = state.validation;
    const ready = !!(v && v.readiness && v.readiness.readyForControlledTesting);
    const deployed = !!(a && String(a.status).toLowerCase() === 'deployed');
    const active = !!(a && a.displayStatus === 'Active') && ready;
    document.querySelectorAll('.lifecycle-step').forEach((el) => el.classList.remove('current'));
    if (deployed) {
      $('lifecycle-deployed').classList.add('current');
      $('lifecycle-badge').textContent = 'Deployed';
      $('lifecycle-badge').className = 'pill pill-violet';
    } else if (active) {
      $('lifecycle-active').classList.add('current');
      $('lifecycle-badge').textContent = 'Active';
      $('lifecycle-badge').className = 'pill pill-green';
    } else {
      $('lifecycle-inactive').classList.add('current');
      $('lifecycle-badge').textContent = 'Inactive';
      $('lifecycle-badge').className = 'pill pill-amber';
    }
    let note = 'No Tressa profile found.';
    if (a) {
      note = `${active ? 'Active' : (deployed ? 'Deployed' : 'Inactive')} — stored status “${a.status}”, derived display “${a.displayStatus}”. `;
      note += ready ? 'The source-derived suite passed, so this supports controlled testing. ' : 'The source-derived suite has not passed, so this is not ready for testing. ';
      note += deployed ? 'A deployment is recorded.' : 'No LiveKit Cloud deployment has been verified; Deployed is not asserted.';
    }
    $('lifecycle-note').textContent = note;
  }

  function renderHealth() {
    const h = state.health || {};
    const a = state.agent;
    $('health-badge').textContent = h.ok ? 'Healthy' : 'Degraded';
    $('health-badge').className = `pill ${h.ok ? 'pill-green' : 'pill-red'} no-dot`;
    const rows = [
      ['Backend', h.ok ? 'Online' : 'Offline'],
      ['Database', h.db || '—'],
      ['Deepgram STT/TTS', h.capabilities && h.capabilities.deepgramStt && h.capabilities.deepgramTts ? 'Configured' : 'Not configured'],
      ['LiveKit', h.capabilities && h.capabilities.livekit ? 'Configured' : 'Not configured'],
      ['External LLM key', h.capabilities && (h.capabilities.openai || h.capabilities.anthropic) ? 'Configured' : 'None detected'],
      ['Tressa sessions', a ? 'See Playground' : 'No profile'],
    ];
    $('health-body').innerHTML = rows.map(([k, val]) => `
      <div class="rounded-lg border border-slate-200 bg-white/60 px-2 py-1.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.08em] text-slate-400">${esc(k)}</div>
        <div class="mt-0.5 text-[10px] font-semibold text-slate-700">${esc(val)}</div>
      </div>`).join('');
    $('deployment-note').textContent = a && String(a.status).toLowerCase() === 'deployed'
      ? 'The local profile is marked deployed. Verify the LiveKit worker/room actually serves Tressa before treating this as live.'
      : 'No LiveKit Cloud deployment has been verified for Tressa. The profile is configured for controlled local testing only.';
  }

  function renderVersions() {
    const versions = state.versions || [];
    $('version-count').textContent = versions.length ? `${versions.length} snapshot(s)` : '';
    $('versions-list').innerHTML = versions.length ? versions.slice(0, 6).map((v) => `
      <div class="rounded-lg border border-slate-200 bg-white/60 p-2">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-1.5">
            <span class="pill ${v.version === (state.agent && state.agent.version) ? 'pill-green' : 'pill-gray'} no-dot">v${v.version}</span>
            <span class="text-[8.5px] text-slate-400">${esc(fmtDate(v.createdAt))}</span>
          </div>
          ${v.version === (state.agent && state.agent.version) ? '<span class="text-[8px] font-bold uppercase tracking-wide text-emerald-600">current</span>'
            : `<button class="btn btn-ghost btn-sm" data-rollback="${v.version}" type="button">Rollback</button>`}
        </div>
        <div class="mt-1 text-[9px] leading-relaxed text-slate-500">${esc(short(v.changeNote || 'No change note', 150))}</div>
      </div>`).join('') : '<div class="text-[9.5px] text-slate-400">No version history.</div>';
  }

  function renderApproval() {
    const a = state.agent;
    const v = state.validation;
    const ready = !!(v && v.readiness && v.readiness.readyForControlledTesting);
    const canApprove = !!(a && ready && String(a.status).toLowerCase() === 'draft');
    const already = !!(a && ['testing', 'approved', 'deployed'].includes(String(a.status).toLowerCase()));
    for (const id of ['approve-btn', 'approve-btn-2']) {
      const btn = $(id);
      btn.disabled = !canApprove;
      btn.textContent = already ? (a && a.status === 'deployed' ? 'Deployed' : 'Active for controlled testing') : 'Approve for controlled testing';
    }
  }

  async function runValidation() {
    if (busy) return;
    busy = true;
    const buttons = [$('validate-btn'), $('validate-btn-2')];
    buttons.forEach((b) => { if (b) { b.disabled = true; b.dataset.label = b.textContent; b.textContent = 'Running…'; } });
    try {
      const report = await API.post('/api/training/validate', state.agent ? { agentId: state.agent.id } : {});
      state.validation = report;
      await loadAll();
      const s = report.summary || {};
      toast(s.failed ? `Validation finished: ${s.passed}/${s.total} passed, ${s.failed} failed.` : `Validation passed: ${s.passed}/${s.total}.`, !!s.failed);
    } catch (err) {
      toast(err.message || 'Validation failed to run.', true);
    } finally {
      busy = false;
      buttons.forEach((b) => { if (b) { b.disabled = false; b.textContent = b.dataset.label || 'Run validation'; } });
    }
  }

  async function approve() {
    if (!state.agent || !state.validation) return;
    const s = state.validation.summary || {};
    if (s.failed || !state.validation.readiness || !state.validation.readiness.readyForControlledTesting) {
      toast('Validation has not passed; approval is blocked.', true);
      return;
    }
    if (!window.confirm('Approve Tressa for controlled testing? This sets the stored status to testing, not deployed.')) return;
    try {
      await API.updateAgent(state.agent.id, {
        status: 'testing',
        changeNote: `Approved for controlled testing after training-material validation ${state.validation.version || ''} (${s.passed}/${s.total} checks). Live voice and deployment remain pending.`,
      });
      toast('Tressa approved for controlled testing. Deployment is still not asserted.');
      await loadAll();
    } catch (err) {
      toast(err.message || 'Approval failed.', true);
    }
  }

  async function reloadKnowledge() {
    try {
      const r = await API.post('/api/training/reload', {});
      toast(`Knowledge reloaded: v${r.version}, ${r.chunks} passages, ${r.tests} tests.`);
      await loadAll();
    } catch (err) {
      toast(err.message || 'Knowledge reload failed.', true);
    }
  }

  async function searchKnowledge(query) {
    const q = String(query || '').trim();
    if (!q) return;
    $('kb-search-btn').disabled = true;
    $('kb-answer-wrap').classList.add('hidden');
    $('kb-results').innerHTML = '<div class="empty-state"><div class="empty-title">Retrieving…</div><div class="empty-sub">Searching the attached corpus.</div></div>';
    try {
      const [answer, results] = await Promise.all([
        API.get(`/api/training/answer?q=${encodeURIComponent(q)}`),
        API.get(`/api/training/search?q=${encodeURIComponent(q)}&limit=6`),
      ]);
      $('kb-answer-wrap').classList.remove('hidden');
      $('kb-answer').textContent = answer.answer || '';
      $('kb-confidence').textContent = answer.confidence || 'none';
      $('kb-confidence').className = `pill ${answer.grounded ? 'pill-green' : 'pill-amber'} no-dot`;
      $('kb-sources').innerHTML = (answer.sources || []).map((s) => `
        <span class="chip source-chip" title="${esc(s.section || '')}">${esc(s.source || '')}${s.slide ? ` · slide ${s.slide}` : ''} · ${esc(s.score)}</span>`).join('');
      const rows = results.results || [];
      $('kb-results').innerHTML = rows.length ? rows.map((r) => `
        <div class="kb-hit">
          <div class="flex flex-wrap items-center justify-between gap-1.5">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="pill pill-violet no-dot">${esc(r.kind || 'passage')}</span>
              <span class="text-[8.5px] font-semibold text-slate-500">${esc(r.source || '')}${(r.answerSlide || r.slide) ? ` · slide ${r.answerSlide || r.slide}` : ''}</span>
            </div>
            <span class="mono text-[8px] text-slate-400">score ${esc(r.score)}</span>
          </div>
          <div class="mt-1 text-[9px] font-bold text-slate-700">${esc(r.section || '')}</div>
          <div class="mt-1 text-[9.5px] leading-relaxed text-slate-500">${esc(short(r.text, 420))}</div>
        </div>`).join('') : '<div class="empty-state"><div class="empty-title">No relevant passage</div><div class="empty-sub">Tressa should say the material does not contain a verified answer and route to a licensed agent.</div></div>';
    } catch (err) {
      $('kb-results').innerHTML = `<div class="rounded-xl border border-red-200 bg-red-50/60 p-3 text-[10px] text-red-700">${esc(err.message || 'Search failed.')}</div>`;
    } finally {
      $('kb-search-btn').disabled = false;
    }
  }

  async function openDocument(file) {
    try {
      const doc = await API.get(`/api/training/documents/${encodeURIComponent(file)}`);
      $('doc-title').textContent = file;
      $('doc-sub').textContent = doc.available ? 'Extracted text · source-preserving' : 'No extracted text';
      $('doc-body').textContent = doc.text || '';
      const dialog = $('doc-dialog');
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', 'open');
    } catch (err) {
      toast(err.message || 'Could not open source document.', true);
    }
  }

  function downloadReport() {
    if (!state.validation) return;
    const blob = new Blob([JSON.stringify(state.validation, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `tressa-validation-${state.validation.version || 'report'}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Event wiring
  $('validate-btn').addEventListener('click', runValidation);
  $('validate-btn-2').addEventListener('click', runValidation);
  $('approve-btn').addEventListener('click', approve);
  $('approve-btn-2').addEventListener('click', approve);
  $('reload-kb-btn').addEventListener('click', reloadKnowledge);
  $('download-report-btn').addEventListener('click', downloadReport);
  $('kb-search-form').addEventListener('submit', (event) => {
    event.preventDefault();
    searchKnowledge($('kb-query').value);
  });
  $('kb-quick').addEventListener('click', (event) => {
    const btn = event.target.closest('[data-query]');
    if (!btn) return;
    $('kb-query').value = btn.dataset.query;
    searchKnowledge(btn.dataset.query);
  });
  $('documents-body').addEventListener('click', (event) => {
    const btn = event.target.closest('[data-doc]');
    if (btn) openDocument(btn.dataset.doc);
  });
  $('doc-close').addEventListener('click', () => {
    const dialog = $('doc-dialog');
    if (dialog.close) dialog.close(); else dialog.removeAttribute('open');
  });
  $('doc-dialog').addEventListener('click', (event) => {
    if (event.target === $('doc-dialog')) $('doc-close').click();
  });
  $('versions-list').addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-rollback]');
    if (!btn || !state.agent) return;
    if (!window.confirm(`Roll back Tressa to version ${btn.dataset.rollback}? This creates a new version.`)) return;
    try {
      await API.rollbackAgent(state.agent.id, Number(btn.dataset.rollback));
      toast(`Rolled back to v${btn.dataset.rollback}. A new version was created.`);
      await loadAll();
    } catch (err) {
      toast(err.message || 'Rollback failed.', true);
    }
  });

  await loadAll();
  // A first query makes the retrieval surface immediately inspectable.
  if (!state.training || state.training.chunkCount) {
    $('kb-query').value = 'What disclosures are required at the start of a Medicare call?';
    searchKnowledge($('kb-query').value);
  }
})();

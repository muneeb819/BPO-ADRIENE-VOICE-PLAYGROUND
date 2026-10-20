/* Security & Reliability */
'use strict';

(async function initSecurity() {
  await Shell.mount('security');

  const $ = (id) => document.getElementById(id);
  let status = null;
  let retention = null;

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '08 — Security & Reliability',
    title: 'Security & Reliability',
    sub: 'Backend-only secrets, validation, redaction, retention, auth readiness, migrations and graceful shutdown.',
    right: `<span class="pill pill-gray" id="hdr-auth">auth</span>
      <span class="pill pill-gray" id="hdr-scan">scan</span>
      <button class="btn btn-dark btn-xs" id="security-refresh" type="button">Refresh</button>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  const KEY_LABELS = {
    DEEPGRAM_API_KEY: 'Deepgram STT + Aura TTS',
    OPENAI_API_KEY: 'OpenAI LLM + TTS',
    ELEVENLABS_API_KEY: 'ElevenLabs TTS',
    ANTHROPIC_API_KEY: 'Anthropic LLM',
  };

  // ---- render status -----------------------------------------------------

  function renderStatus() {
    if (!status) return;
    const keys = status.keys || {};
    $('secret-key-lines').innerHTML = Object.entries(KEY_LABELS).map(([key, label]) => {
      const present = !!keys[key];
      return `<div><span class="text-violet-300">${key}</span>=<span class="${present ? 'text-emerald-400' : 'text-slate-500'}">${present ? '••••••••' : 'not set'}</span> <span class="text-slate-500">(${label})</span></div>`;
    }).join('');

    const scan = status.frontendScan || { clean: true, findings: [], scannedFiles: 0 };
    const scanPill = scan.clean ? 'pill-green' : 'pill-red';
    const scanText = scan.clean ? '✓ No credentials in bundle' : `✗ ${scan.findings.length} finding${scan.findings.length === 1 ? '' : 's'}`;
    $('scan-result').innerHTML = `<span class="pill ${scanPill}">${scanText}</span>` +
      (!scan.clean
        ? `<div class="mt-1.5 space-y-1 text-[8.5px] text-red-700">${scan.findings.map((f) => `<div>${UI.esc(f.file)} · ${UI.esc(f.pattern)}</div>`).join('')}</div>`
        : '');
    $('scan-meta').textContent = `${scan.scannedFiles} frontend files scanned`;

    $('redaction-sample').textContent = JSON.stringify(status.redactionSample || {}, null, 2);
    $('rate-limit-text').textContent = status.rateLimit || '—';

    $('auth-mode').textContent = status.authEnabled ? 'Bearer token' : 'Localhost (no auth)';
    $('auth-mode').className = `pill ${status.authEnabled ? 'pill-green' : 'pill-gray'}`;
    if (status.authEnabled) {
      $('auth-warning').className = 'mt-2 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-[8.5px] leading-relaxed text-emerald-700';
      $('auth-warning').textContent = '✓ Bearer authentication is enforced on /api/*.';
    } else {
      $('auth-warning').className = 'mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-[8.5px] leading-relaxed text-amber-800';
      $('auth-warning').textContent = '⚠ Dashboard must not be exposed beyond localhost without auth.';
    }

    $('hdr-auth').textContent = status.authEnabled ? 'auth: bearer' : 'localhost';
    $('hdr-auth').className = `pill ${status.authEnabled ? 'pill-green' : 'pill-gray'}`;
    $('hdr-scan').textContent = scan.clean ? 'scan clean' : 'scan findings';
    $('hdr-scan').className = `pill ${scan.clean ? 'pill-green' : 'pill-red'}`;
    $('telephony-posture').textContent = status.telephonyEnabled ? 'enabled' : 'disabled';
    $('telephony-posture').className = `pill ${status.telephonyEnabled ? 'pill-amber' : 'pill-red'} no-dot`;
  }

  function renderRetention(data) {
    retention = data;
    $('audio-days').value = data.audioRetentionDays;
    $('transcript-days').value = data.transcriptRetentionDays;
    $('auto-delete').checked = !!data.autoDeleteEnabled;
    $('consent-disclosure').value = data.consentDisclosure || '';
    $('retention-updated').textContent = data.updatedAt ? UI.timeAgo(data.updatedAt) : '—';
  }

  async function loadStatus() {
    const [s, r] = await Promise.all([API.securityStatus(), API.retention()]);
    status = s;
    renderStatus();
    renderRetention(r);
  }

  // ---- health ------------------------------------------------------------

  async function checkHealth(showToast = false) {
    try {
      const health = await API.health();
      $('ops-health').textContent = health.ok ? 'ok' : 'degraded';
      $('ops-health').className = `pill ${health.ok ? 'pill-green' : 'pill-red'}`;
      $('ops-db').textContent = health.db ? `DB: ${health.db}` : 'SQLite';
      $('ops-db').className = 'pill pill-violet';
      if (showToast) UI.toast(`${health.ok ? 'Health OK' : 'Health degraded'} · v${health.version}`, health.ok ? 'success' : 'error');
    } catch (err) {
      $('ops-health').textContent = 'unreachable';
      $('ops-health').className = 'pill pill-red';
      if (showToast) UI.toast(err.message, 'error');
    }
  }

  // ---- self test ---------------------------------------------------------

  function renderSelftest(data) {
    const panel = $('selftest-panel');
    panel.classList.remove('hidden');
    const allPass = data.passed === data.total;
    $('selftest-summary').textContent = `${data.passed}/${data.total} passed`;
    $('selftest-summary').className = `pill ${allPass ? 'pill-green' : 'pill-red'}`;
    $('selftest-time').textContent = `run ${UI.fmtTime(data.generatedAt)}`;
    $('selftest-results').innerHTML = (data.results || []).map((r) => `<div class="rounded-lg border px-2.5 py-2 ${r.pass ? 'border-emerald-200 bg-emerald-50/60' : 'border-red-200 bg-red-50'}">
      <div class="flex items-center gap-1.5">
        <span class="text-[8.5px] font-extrabold ${r.pass ? 'text-emerald-700' : 'text-red-700'}">${r.pass ? 'PASS' : 'FAIL'}</span>
        <span class="text-[9.5px] font-bold text-slate-700">${UI.esc(r.test)}</span>
        <span class="ml-auto font-mono text-[8px] text-slate-400">${UI.esc(r.expected)} → ${UI.esc(r.actual)}</span>
      </div>
      ${r.detail ? `<div class="mt-0.5 text-[8.5px] leading-relaxed text-slate-500">${UI.esc(r.detail)}</div>` : ''}
    </div>`).join('');
  }

  // ---- events ------------------------------------------------------------

  $('security-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    try {
      await loadStatus();
      await checkHealth();
      UI.toast('Security status refreshed', 'success');
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  $('selftest-btn').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    UI.setBusy(btn, true, 'Running tests');
    try {
      const data = await API.securitySelftest();
      renderSelftest(data);
      UI.toast(`${data.passed}/${data.total} security checks passed`, data.passed === data.total ? 'success' : 'error');
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  $('retention-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const audio = Number($('audio-days').value);
    const transcript = Number($('transcript-days').value);
    if (!Number.isInteger(audio) || audio < 1 || audio > 365 || !Number.isInteger(transcript) || transcript < 1 || transcript > 365) {
      UI.toast('Retention must be whole days between 1 and 365.', 'error');
      return;
    }
    const btn = $('save-retention');
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
      const saved = await API.saveRetention({
        audioRetentionDays: audio,
        transcriptRetentionDays: transcript,
        autoDeleteEnabled: $('auto-delete').checked,
        consentDisclosure: $('consent-disclosure').value,
      });
      renderRetention(saved);
      UI.toast('Retention policy saved', 'success');
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save Policy';
    }
  });

  $('delete-artifacts').addEventListener('click', async (event) => {
    if (!window.confirm('Delete all local sessions, mock telephony logs and test runs? This cannot be undone.')) return;
    const btn = event.currentTarget;
    UI.setBusy(btn, true, 'Deleting');
    try {
      const result = await API.deleteAllSessions();
      UI.toast(`Deleted ${result.deletedSessions} sessions, ${result.deletedTelephonyLogs} logs and all test runs`, 'success');
      await loadStatus();
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  $('health-btn').addEventListener('click', () => checkHealth(true));

  // ---- boot --------------------------------------------------------------

  try {
    await loadStatus();
  } catch (err) {
    UI.toast(err.message, 'error');
    $('scan-result').innerHTML = `<span class="pill pill-red">status unavailable</span>`;
  }
  await checkHealth();
})();

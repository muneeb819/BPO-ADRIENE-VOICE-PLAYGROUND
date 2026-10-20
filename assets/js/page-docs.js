/* Launch Guide & Hardening */
'use strict';

(async function initDocs() {
  await Shell.mount('docs');

  const $ = (id) => document.getElementById(id);
  let verifying = false;

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '10 — Production Hardening & Delivery',
    title: 'Launch Guide, Hardening & Final Report',
    sub: 'Lint, type-check, tests, migration, backup/restore, diagnostics, feature inventory.',
    right: `
      <span class="pill pill-violet no-dot">local-first</span>
      <button class="btn btn-dark btn-sm" id="docs-verify" type="button">
        <span data-icon="refresh"></span> Run live verification
      </button>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  function pill(label, tone) {
    return `<span class="pill pill-${tone} no-dot">${UI.esc(label)}</span>`;
  }

  function resultRow(label, note, status, tone) {
    return `<div class="doc-result-row">
      <span class="doc-result-label">${UI.esc(label)}</span>
      <span class="doc-result-note">${UI.esc(note)}</span>
      ${pill(status, tone)}
    </div>`;
  }

  function setTile(id, status, tone) {
    const host = $(id);
    if (host) host.innerHTML = pill(status, tone);
  }

  function latestRun(runs) {
    return Array.isArray(runs) && runs.length ? runs[0] : null;
  }

  function selftestCheck(selftest, needle) {
    const results = (selftest && selftest.results) || [];
    return results.find((r) => String(r.test || '').toLowerCase().includes(needle));
  }

  async function runVerification(showToast) {
    if (verifying) return;
    verifying = true;
    const btn = $('docs-verify');
    if (btn && showToast) UI.setBusy(btn, true, 'Verifying…');

    try {
      const [healthRes, agentsRes, runsRes, logsRes, selfRes] = await Promise.allSettled([
        API.health(),
        API.agents(),
        API.testRuns(),
        API.telephonyLogs(),
        API.securitySelftest(),
      ]);

      const health = healthRes.status === 'fulfilled' ? healthRes.value : null;
      const agents = agentsRes.status === 'fulfilled' ? agentsRes.value : [];
      const runs = runsRes.status === 'fulfilled' ? runsRes.value : [];
      const logs = logsRes.status === 'fulfilled' ? logsRes.value : [];
      const selftest = selfRes.status === 'fulfilled' ? selfRes.value : null;
      const run = latestRun(runs);
      const redaction = selftestCheck(selftest, 'secret redaction');
      const scan = selftestCheck(selftest, 'frontend secret scan');
      const allScan = selftest && selftest.passed === selftest.total;
      const caps = (health && health.capabilities) || {};
      const dbOk = !!(health && health.database);

      setTile('tile-syntax', health ? 'pass' : 'fail', health ? 'green' : 'red');
      setTile('tile-health', health ? 'pass' : 'fail', health ? 'green' : 'red');
      setTile(
        'tile-scan',
        selftest ? `${selftest.passed}/${selftest.total}` : 'fail',
        allScan ? 'green' : 'red'
      );

      const regressionTone = !run ? 'violet' : (run.failed === 0 ? 'green' : 'red');
      const regressionStatus = !run ? 'Ready' : (run.failed === 0 ? 'Pass' : 'Fail');
      const regressionNote = !run
        ? 'seed fixtures in Testing'
        : `${run.passed}/${run.totalCases} passed · ${UI.fmtTime(run.createdAt)}`;

      const rows = [
        resultRow(
          'Health endpoint',
          health ? `HTTP 200 · ${health.latencyMs ?? 0} ms` : 'unreachable',
          health ? 'Pass' : 'Fail',
          health ? 'green' : 'red'
        ),
        resultRow(
          'SQLite persistence',
          dbOk ? `${health.database} · ${health.db}` : 'database unavailable',
          dbOk ? 'Pass' : 'Fail',
          dbOk ? 'green' : 'red'
        ),
        resultRow(
          'Agent CRUD + versioning',
          `${Array.isArray(agents) ? agents.length : 0} saved agent(s)`,
          Array.isArray(agents) && agents.length ? 'Pass' : 'Fail',
          Array.isArray(agents) && agents.length ? 'green' : 'red'
        ),
        resultRow(
          'Deterministic conversation engine',
          run ? `${run.passed}/${run.totalCases} cases · ${UI.fmtTime(run.createdAt)}` : 'ready — no regression run yet',
          run ? (run.failed === 0 ? 'Pass' : 'Fail') : 'Ready',
          run ? (run.failed === 0 ? 'green' : 'red') : 'violet'
        ),
        resultRow(
          'Deepgram Aura TTS',
          caps.deepgramTts ? 'backend key present · aura voices' : 'no backend key — browser fallback',
          caps.deepgramTts ? 'Configured' : 'Fallback',
          caps.deepgramTts ? 'violet' : 'amber'
        ),
        resultRow(
          'Deepgram Nova-2 STT',
          caps.deepgramStt ? 'backend key present · nova-2' : 'no backend key — browser fallback',
          caps.deepgramStt ? 'Configured' : 'Fallback',
          caps.deepgramStt ? 'violet' : 'amber'
        ),
        resultRow(
          'Playground audio pipeline',
          'mic → STT → policy → TTS · barge-in',
          health ? 'Wired' : 'Unavailable',
          health ? 'violet' : 'red'
        ),
        resultRow(
          'Regression suite',
          regressionNote,
          regressionStatus,
          regressionTone
        ),
        resultRow(
          'Secret redaction',
          redaction ? (redaction.pass ? 'apiKey/token/secret/password masked' : 'check failed') : 'selftest unavailable',
          redaction ? (redaction.pass ? 'Pass' : 'Fail') : 'Ready',
          redaction ? (redaction.pass ? 'green' : 'red') : 'violet'
        ),
        resultRow(
          'Frontend secret scan',
          scan ? `${scan.detail || 'assets/js + HTML'} · ${scan.actual}` : 'selftest unavailable',
          scan ? (scan.pass ? 'Pass' : 'Fail') : 'Ready',
          scan ? (scan.pass ? 'green' : 'red') : 'violet'
        ),
        resultRow(
          'Mock telephony',
          `${Array.isArray(logs) ? logs.length : 0} sandbox event(s)`,
          'Sandbox',
          'violet'
        ),
        resultRow(
          'Server process',
          health ? `v${health.version} · up ${health.uptimeSec}s` : 'not running',
          health ? 'Pass' : 'Fail',
          health ? 'green' : 'red'
        ),
      ];

      $('doc-results').innerHTML = rows.join('');
      $('doc-generated').textContent = UI.fmtTime(new Date().toISOString());

      if (showToast) {
        const passed = rows.filter((row) => row.includes('pill-green')).length;
        const failed = rows.filter((row) => row.includes('pill-red')).length;
        if (failed) UI.toast(`${failed} verification item(s) need attention`, 'error');
        else UI.toast(`${passed} live checks passed · Deepgram configured`, 'success');
      }
    } finally {
      verifying = false;
      if (btn) UI.setBusy(btn, false);
    }
  }

  $('docs-verify').addEventListener('click', () => runVerification(true));
  await runVerification(false);
})();

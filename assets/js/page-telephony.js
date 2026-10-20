/* Telephony — mock SIP / VICIdial */
'use strict';

(async function initTelephony() {
  await Shell.mount('telephony');

  const $ = (id) => document.getElementById(id);
  let sessions = [];
  let agents = [];
  let logs = [];

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  const agentName = (id) => {
    const a = agents.find((x) => x.id === id);
    return a ? a.name : 'Standalone mock';
  };

  // ---- logs --------------------------------------------------------------

  function logCard(ev) {
    const payload = JSON.stringify(ev.payload || {});
    return `<div class="rounded-xl border border-slate-300 bg-white px-3 py-2.5">
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="font-mono text-[10px] font-bold tracking-tight text-slate-800">${UI.esc(ev.eventType)}</span>
        ${UI.statusPill(ev.status)}
        <span class="ml-auto font-mono text-[8px] text-slate-400">${UI.esc(ev.correlationId)}</span>
      </div>
      <div class="mt-1 text-[8.5px] text-slate-400">Provider: ${UI.esc(ev.provider)} • ${UI.esc(ev.direction)} • ${UI.fmtDate(ev.createdAt)}</div>
      <pre class="mt-1.5 overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 font-mono text-[8.5px] leading-relaxed text-slate-600">${UI.esc(payload)}</pre>
      <div class="mt-1 break-all font-mono text-[7.5px] text-slate-400">sessionId: ${UI.esc(ev.sessionId || 'standalone')}</div>
    </div>`;
  }

  function renderLogs() {
    $('log-count').textContent = `${logs.length} event${logs.length === 1 ? '' : 's'}`;
    if (!logs.length) {
      $('telephony-logs').innerHTML = `<div class="empty-state">
        <div class="empty-icon">${Shell.icon('phone')}</div>
        <div class="empty-title">No telephony logs</div>
        <div class="empty-sub">Run a mock call to verify the adapter and see correlation IDs.</div>
      </div>`;
      return;
    }
    const sorted = [...logs].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).slice(0, 80);
    $('telephony-logs').innerHTML = sorted.map(logCard).join('');
  }

  async function loadLogs() {
    logs = await API.telephonyLogs();
    renderLogs();
  }

  // ---- sessions ----------------------------------------------------------

  function renderSessions() {
    const select = $('telephony-session');
    const current = select.value;
    select.innerHTML = '<option value="">No session (standalone mock)</option>' + sessions
      .map((s) => `<option value="${s.id}">${UI.esc(agentName(s.agentId))} · ${UI.shortId(s.id)} · ${s.status} · ${s.userInputMode}</option>`)
      .join('');
    if (current) select.value = current;
    const wanted = UI.getParam('sessionId');
    if (wanted && sessions.find((s) => s.id === wanted)) select.value = wanted;
  }

  // ---- mock actions ------------------------------------------------------

  function showNotice(text, type = 'success') {
    const box = $('mock-notice');
    box.className = `mt-2 rounded-lg border px-2.5 py-2 text-[9.5px] leading-relaxed ${type === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-amber-200 bg-amber-50 text-amber-800'}`;
    box.textContent = text;
  }

  async function runMock(transfer, button) {
    const other = transfer ? $('mock-call-btn') : $('mock-transfer-btn');
    other.disabled = true;
    UI.setBusy(button, true, transfer ? 'Transferring' : 'Dialing');
    const sessionId = $('telephony-session').value || null;
    try {
      const body = { requestTransfer: transfer };
      if (sessionId) body.sessionId = sessionId;
      const result = await API.mockCall(body);
      const blocked = (result.events || []).find((ev) => ev.eventType === 'mock_transfer_blocked');
      if (blocked) {
        showNotice(`${transfer ? 'Transfer' : 'Call'} blocked by consent policy: ${blocked.payload?.reason || 'missing_consent'} • correlation ${result.correlationId}`, 'warning');
        UI.toast('Mock transfer blocked by consent policy', 'error');
      } else {
        showNotice(`${transfer ? 'Mock transfer completed' : 'Mock call completed'} • ${result.events.length} lifecycle events • correlation ${result.correlationId}`, 'success');
        UI.toast(`Mock ${transfer ? 'transfer' : 'call'} stored · ${result.correlationId}`, 'success');
      }
      await loadLogs();
      $('telephony-logs').scrollTop = 0;
    } catch (err) {
      showNotice(err.message, 'warning');
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(button, false);
      other.disabled = false;
    }
  }

  $('mock-call-btn').addEventListener('click', (event) => runMock(false, event.currentTarget));
  $('mock-transfer-btn').addEventListener('click', (event) => runMock(true, event.currentTarget));
  $('refresh-logs').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    try {
      await loadLogs();
      UI.toast('Telephony log refreshed', 'success');
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  // ---- enable live (always blocked) --------------------------------------

  $('enable-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const resultBox = $('enable-result');
    resultBox.classList.remove('hidden');
    if (!$('operator-auth').checked) {
      resultBox.className = 'mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[9px] leading-relaxed text-amber-800';
      resultBox.textContent = 'Confirm operator authorization before requesting live dialing. Mock mode remains active.';
      return;
    }
    const btn = $('enable-btn');
    btn.disabled = true;
    btn.textContent = 'Requesting…';
    try {
      await API.enableTelephony({
        sipRealm: $('sip-realm').value.trim(),
        vicidialUrl: $('vicidial-url').value.trim(),
        authorized: true,
      });
      resultBox.className = 'mt-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-2 text-[9px] leading-relaxed text-red-700';
      resultBox.textContent = 'Unexpected: live telephony should remain blocked in this build. Do not dial real numbers.';
    } catch (err) {
      resultBox.className = 'mt-2 rounded-lg border border-red-200 bg-red-50 px-2.5 py-2 text-[9px] leading-relaxed text-red-700';
      resultBox.textContent = `${err.message} Mock mode remains active; no SIP/PSTN connection was attempted.`;
      UI.toast('Live dialing remains blocked', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Enable Live Dialing (Blocked in Playground)';
    }
  });

  // ---- boot --------------------------------------------------------------

  try {
    const [sessionList, agentList] = await Promise.all([API.sessions('?limit=50'), API.agents()]);
    sessions = sessionList;
    agents = agentList;
    renderSessions();
  } catch (err) {
    UI.toast(err.message, 'error');
  }

  try {
    await loadLogs();
  } catch (err) {
    UI.toast(err.message, 'error');
  }

  try {
    const health = await API.health();
    const live = health.telephony === 'enabled';
    $('telephony-live-pill').textContent = live ? 'Live dialing: config enabled (mock adapter)' : 'Live dialing: disabled';
    $('telephony-live-pill').className = `pill ${live ? 'pill-amber' : 'pill-red'} no-dot`;
  } catch {
    $('telephony-live-pill').textContent = 'Live dialing: API offline';
    $('telephony-live-pill').className = 'pill pill-red no-dot';
  }
})();

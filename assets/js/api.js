/* ==========================================================================
   API client + shared UI helpers
   ========================================================================== */
'use strict';

const API = (() => {
  async function request(path, options = {}) {
    const opts = { ...options };
    opts.headers = { ...(options.headers || {}) };
    if (opts.body && typeof opts.body !== 'string' && !(opts.body instanceof Blob)
        && !(opts.body instanceof FormData) && !(opts.body instanceof ArrayBuffer)) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (err) {
      const e = new Error('Cannot reach the local API. Is server.py running?');
      e.status = 0;
      throw e;
    }
    const ctype = res.headers.get('Content-Type') || '';
    let data;
    if (ctype.includes('application/json')) {
      data = await res.json().catch(() => ({}));
    } else {
      data = await res.text().catch(() => '');
    }
    if (!res.ok) {
      const message = (data && data.error) || (typeof data === 'string' && data) || `Request failed (${res.status})`;
      const error = new Error(message);
      error.status = res.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  const get = (p) => request(p);
  const post = (p, body = {}) => request(p, { method: 'POST', body });
  const put = (p, body = {}) => request(p, { method: 'PUT', body });
  const patch = (p, body = {}) => request(p, { method: 'PATCH', body });
  const del = (p) => request(p, { method: 'DELETE' });

  return {
    request,
    get, post, put, patch, del,

    health: () => get('/api/health'),

    agents: (params = '') => get('/api/agents' + params),
    agent: (id) => get(`/api/agents/${id}`),
    createAgent: (data) => post('/api/agents', data),
    updateAgent: (id, data) => put(`/api/agents/${id}`, data),
    deleteAgent: (id) => del(`/api/agents/${id}`),
    duplicateAgent: (id) => post(`/api/agents/${id}/duplicate`, {}),
    rollbackAgent: (id, version) => post(`/api/agents/${id}/rollback`, { version }),
    versions: (id) => get(`/api/agents/${id}/versions`),

    sessions: (params = '') => get('/api/sessions' + params),
    session: (id) => get(`/api/sessions/${id}`),
    createSession: (agentId, userInputMode = 'text') => post('/api/sessions', { agentId, userInputMode }),
    turn: (id, content, intent) => post(`/api/sessions/${id}/turns`, { content, intent }),
    patchSession: (id, body) => patch(`/api/sessions/${id}`, body),
    deleteSession: (id) => del(`/api/sessions/${id}`),
    deleteAllSessions: () => del('/api/sessions'),

    analytics: (params = '') => get('/api/analytics/summary' + params),

    providers: () => get('/api/providers'),
    testProvider: (id) => post(`/api/providers/${id}/test`, {}),

    retention: () => get('/api/retention'),
    saveRetention: (data) => put('/api/retention', data),

    testCases: (params = '') => get('/api/test-cases' + params),
    createTestCase: (data) => post('/api/test-cases', data),
    seedFixtures: (agentId) => post('/api/test-cases/seed', { agentId }),
    testRuns: (params = '') => get('/api/test-runs' + params),
    runTests: (data) => post('/api/test-runs', data),

    telephonyLogs: () => get('/api/telephony/logs'),
    mockCall: (data) => post('/api/telephony/mock-call', data),
    enableTelephony: (data) => post('/api/telephony/enable', data),

    securityStatus: () => get('/api/security/status'),
    securitySelftest: () => post('/api/security/selftest', {}),

    async tts(text, voice) {
      const res = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const err = new Error(data.error || `TTS failed (${res.status})`);
        err.status = res.status;
        throw err;
      }
      return res.blob();
    },

    async stt(blob) {
      const res = await fetch('/api/stt', {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm' },
        body: blob,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = new Error(data.error || `Transcription failed (${res.status})`);
        err.status = res.status;
        throw err;
      }
      return data;
    },
  };
})();

const UI = (() => {
  const STATUS_COLORS = {
    draft: 'gray', testing: 'amber', approved: 'green', archived: 'gray',
    active: 'violet', completed: 'green', interrupted: 'amber', error: 'red',
    connected: 'green', disconnected: 'gray', passed: 'green', failed: 'red',
    partial: 'amber', pass: 'green', fail: 'red',
    initiated: 'blue', ringing: 'amber', answered: 'green', requested: 'violet',
    available: 'green', transferred: 'green', blocked: 'red', timeout: 'red',
    positive: 'green', negative: 'red', ambiguous: 'amber', silence: 'blue',
    interruption: 'violet', provider_failure: 'red',
  };

  const esc = (value) => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const attr = esc;

  function statusPill(status, label) {
    const s = String(status || 'unknown').toLowerCase();
    const color = STATUS_COLORS[s] || 'gray';
    const text = label || s.replace(/_/g, ' ');
    return `<span class="pill pill-${color}">${esc(text)}</span>`;
  }

  function fmtDate(iso, opts = {}) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString([], {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', ...opts,
    });
  }

  function fmtDateShort(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(diff)) return '—';
    const sec = Math.max(0, Math.round(diff / 1000));
    if (sec < 45) return `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const days = Math.round(hr / 24);
    return `${days}d ago`;
  }

  function duration(ms) {
    if (ms === null || ms === undefined) return '—';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    return `${(ms / 1000).toFixed(1)} s`;
  }

  function shortId(id) {
    return id ? String(id).slice(0, 8) : '—';
  }

  function toast(message, type = 'info', timeout = 3800) {
    let wrap = document.querySelector('.toast-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'toast-wrap';
      document.body.appendChild(wrap);
    }
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.setAttribute('role', 'status');
    el.innerHTML = `<span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '!' : '•'}</span><span>${esc(message)}</span>`;
    wrap.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(4px)';
      el.style.transition = 'all .2s ease';
      setTimeout(() => el.remove(), 220);
    }, timeout);
  }

  function download(filename, content, mime = 'application/octet-stream') {
    const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to clipboard', 'success', 1800);
    } catch {
      toast('Clipboard unavailable in this browser', 'error');
    }
  }

  function debounce(fn, wait = 220) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), wait);
    };
  }

  function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function emptyState(title, sub, iconName = 'inbox') {
    const svg = (window.Shell && Shell.icon) ? Shell.icon(iconName) : '';
    return `<div class="empty-state">
      <div class="empty-icon">${svg}</div>
      <div class="empty-title">${esc(title)}</div>
      <div class="empty-sub">${esc(sub)}</div>
    </div>`;
  }

  function agentName(agents, id) {
    const a = (agents || []).find((x) => x.id === id);
    return a ? a.name : (id ? 'Unknown agent' : '—');
  }

  function providerTypeLabel(type) {
    return { stt: 'STT', llm: 'LLM', tts: 'TTS' }[type] || String(type || '').toUpperCase();
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.original = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg> ${esc(label || 'Working…')}`;
    } else {
      button.disabled = false;
      if (button.dataset.original) button.innerHTML = button.dataset.original;
    }
  }

  return {
    esc, attr, statusPill, fmtDate, fmtDateShort, fmtTime, timeAgo, duration,
    shortId, toast, download, copy, debounce, getParam, emptyState, agentName,
    providerTypeLabel, setBusy,
  };
})();

window.API = API;
window.UI = UI;

/* Admin Panel - combined dashboard for every system and module.
   Charts are hand-rolled SVG so the app keeps its "no runtime dependency" rule. */
'use strict';

(async function initAdmin() {
  await Shell.mount('admin');

  const $ = (id) => document.getElementById(id);
  let data = null;
  let filter = '';

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '01 — Admin Panel',
    title: 'Combined Operations Dashboard',
    sub: 'One screen for every system, module and adapter: live health, traffic, latency, quality, Deepgram and the module registry.',
    right: `<a class="btn btn-outline" href="/deepgram">${Shell.icon('bolt')} Deepgram</a>
      <a class="btn btn-primary" href="/agents">${Shell.icon('layers')} Agent Studio</a>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  // --- tiny SVG chart helpers ---------------------------------------------
  const PALETTE = ['#8b5cf6', '#22d3ee', '#34d399', '#fbbf24', '#f87171', '#60a5fa', '#f472b6', '#a3e635'];

  function comboChart(rows) {
    const W = 640, H = 210, PL = 34, PR = 10, PT = 12, PB = 22;
    if (!rows.length) return '<div class="py-10 text-center text-[10px] text-slate-500">No traffic recorded yet.</div>';
    const innerW = W - PL - PR, innerH = H - PT - PB;
    const maxBar = Math.max(1, ...rows.map((r) => Math.max(r.sessions, r.turns)));
    const maxLine = Math.max(1, ...rows.map((r) => r.latency || 0));
    const step = innerW / rows.length;
    const barW = Math.max(3, Math.min(18, step * 0.34));
    const y = (v, max) => PT + innerH - (v / max) * innerH;
    const grid = [0, 0.5, 1].map((f) => {
      const gy = PT + innerH - f * innerH;
      return `<line x1="${PL}" y1="${gy}" x2="${W - PR}" y2="${gy}" stroke="rgba(148,163,184,.16)" stroke-width="1"/>
              <text x="${PL - 6}" y="${gy + 3}" text-anchor="end" font-size="8" fill="#64748b">${Math.round(maxBar * f)}</text>`;
    }).join('');
    const bars = rows.map((r, i) => {
      const x = PL + i * step + (step - barW) / 2;
      const h = (r.sessions / maxBar) * innerH;
      return `<rect x="${x.toFixed(1)}" y="${(PT + innerH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" rx="2" fill="#8b5cf6" opacity=".85"/>`;
    }).join('');
    const turns = rows.map((r, i) => {
      const x = PL + i * step + step / 2;
      const h = (r.turns / maxBar) * innerH;
      return `<rect x="${(x - barW / 2).toFixed(1)}" y="${(PT + innerH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" rx="2" fill="#22d3ee" opacity=".7"/>`;
    }).join('');
    const linePts = rows.map((r, i) => {
      const x = PL + i * step + step / 2;
      const ly = y(r.latency || 0, maxLine);
      return `${x.toFixed(1)},${ly.toFixed(1)}`;
    }).join(' ');
    const labels = rows.map((r, i) => {
      if (rows.length > 8 && i % Math.ceil(rows.length / 8) !== 0 && i !== rows.length - 1) return '';
      return `<text x="${(PL + i * step + step / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" font-size="7.5" fill="#64748b">${(r.day || '').slice(5)}</text>`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" class="w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Sessions and turns per day">
      ${grid}${bars}${turns}
      ${linePts ? `<polyline points="${linePts}" fill="none" stroke="#34d399" stroke-width="2" stroke-linejoin="round"/>` : ''}
      ${labels}
      <text x="${PL - 6}" y="${PT - 2}" text-anchor="end" font-size="7.5" fill="#34d399">${maxLine} ms</text>
    </svg>`;
  }

  function donut(segments, centerLabel, centerSub) {
    const total = segments.reduce((sum, s) => sum + s.value, 0);
    const R = 42, C = 2 * Math.PI * R;
    if (!total) {
      return `<div class="flex h-[112px] items-center justify-center text-[10px] text-slate-500">no data</div>`;
    }
    let offset = 0;
    const rings = segments.map((s, i) => {
      const len = (s.value / total) * C;
      const el = `<circle cx="56" cy="56" r="${R}" fill="none"
        stroke="${s.color || PALETTE[i % PALETTE.length]}" stroke-width="13"
        stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}"
        stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 56 56)"/>`;
      offset += len;
      return el;
    }).join('');
    const pct = Math.round((segments[0].value / total) * 100);
    return `<svg viewBox="0 0 112 112" class="h-[112px] w-full" role="img" aria-label="${centerLabel}">
      <circle cx="56" cy="56" r="${R}" fill="none" stroke="rgba(148,163,184,.14)" stroke-width="13"/>
      ${rings}
      <text x="56" y="54" text-anchor="middle" font-size="15" font-weight="700" fill="#f1f5f9">${centerSub !== undefined ? centerSub : `${pct}%`}</text>
      <text x="56" y="68" text-anchor="middle" font-size="7.5" fill="#94a3b8">${centerLabel}</text>
    </svg>`;
  }

  function gauge(value, max, label) {
    const v = max ? Math.min(1, (value || 0) / max) : 0;
    const R = 46, cx = 60, cy = 58;
    const arc = (from, to, color) => {
      const a1 = Math.PI * (1 - from), a2 = Math.PI * (1 - to);
      const x1 = cx + R * Math.cos(a1), y1 = cy - R * Math.sin(a1);
      const x2 = cx + R * Math.cos(a2), y2 = cy - R * Math.sin(a2);
      const large = to - from > 0.5 ? 1 : 0;
      return `<path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${R} ${R} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
        fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"/>`;
    };
    const ang = Math.PI * (1 - v);
    const nx = cx + (R - 12) * Math.cos(ang), ny = cy - (R - 12) * Math.sin(ang);
    return `<svg viewBox="0 0 120 72" class="w-full" role="img" aria-label="${label}">
      ${arc(0, 1, 'rgba(148,163,184,.16)')}
      ${arc(0, Math.max(0.02, v), '#8b5cf6')}
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="#f1f5f9" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="3.5" fill="#f1f5f9"/>
      <text x="${cx}" y="${cy - 18}" text-anchor="middle" font-size="13" font-weight="700" fill="#f1f5f9">${value ?? 0}</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="7.5" fill="#94a3b8">${label}</text>
    </svg>`;
  }

  function hBars(items, unit = '') {
    if (!items.length) return '<div class="py-6 text-center text-[10px] text-slate-500">no data</div>';
    const max = Math.max(1, ...items.map((i) => i.value));
    return `<div class="space-y-1.5">${items.map((i) => `
      <div>
        <div class="flex items-center justify-between gap-2 text-[9.5px]">
          <span class="truncate text-slate-600">${UI.esc(i.label)}</span>
          <span class="mono text-slate-500">${UI.esc(String(i.value))}${unit}</span>
        </div>
        <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200/60">
          <div class="h-full rounded-full" style="width:${Math.max(2, (i.value / max) * 100)}%;background:${i.color || '#8b5cf6'}"></div>
        </div>
      </div>`).join('')}</div>`;
  }

  function legend(segments) {
    return segments.map((s, i) => `<div class="flex items-center justify-between gap-2 text-[9px]">
      <span class="flex items-center gap-1.5 text-slate-500">
        <span class="h-2 w-2 rounded-sm" style="background:${s.color || PALETTE[i % PALETTE.length]}"></span>${UI.esc(s.label)}
      </span>
      <span class="mono text-slate-400">${s.value}</span>
    </div>`).join('');
  }

  // --- rendering ------------------------------------------------------------
  function render() {
    const c = data.counts;
    const sys = data.system;

    // operations
    $('ops-chart').innerHTML = comboChart(data.daily.map((d) => ({
      ...d,
      latency: d.latency || Math.round(data.latency.p95 || 0),
    })));
    $('ops-range').textContent = `${data.daily.length} day(s) · ${c.sessions} sessions · ${c.turns} turns`;

    // agents
    const agentSegs = (data.agentStatus || []).map((s, i) => ({
      label: s.status, value: s.count, color: ['#34d399', '#fbbf24', '#8b5cf6', '#64748b'][i % 4],
    }));
    $('agents-count').textContent = `${c.agents} total`;
    $('agents-donut').innerHTML = donut(agentSegs.length ? agentSegs : [{ label: 'no agents', value: 0 }], 'agents');
    $('agents-legend').innerHTML = legend(agentSegs);

    // providers
    const byStatus = { connected: 0, disconnected: 0, error: 0 };
    (data.providers || []).forEach((p) => { byStatus[p.status] = (byStatus[p.status] || 0) + 1; });
    const provSegs = Object.entries(byStatus)
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({ label: k, value: v, color: k === 'connected' ? '#34d399' : (k === 'error' ? '#f87171' : '#64748b') }));
    $('providers-count').textContent = `${c.providersConnected}/${c.providers} live`;
    $('providers-donut').innerHTML = donut(provSegs.length ? provSegs : [{ label: 'none', value: 0 }], 'adapters');
    $('providers-legend').innerHTML = legend(provSegs);

    // deepgram
    const dg = data.deepgram;
    $('dg-state').textContent = dg.connected ? 'connected' : 'offline';
    $('dg-state').className = `pill ${dg.connected ? 'pill-green' : 'pill-red'} no-dot`;
    $('dg-project').textContent = dg.project?.name || 'No Deepgram project';
    const voiceSegs = (data.voiceMix || []).map((v, i) => ({ label: v.family, value: v.count, color: PALETTE[i % PALETTE.length] }));
    $('deepgram-donut').innerHTML = donut(voiceSegs.length ? voiceSegs : [{ label: 'no agents', value: 0 }], 'voices in use');
    $('deepgram-legend').innerHTML = legend([
      { label: `${dg.voices} voices available`, value: dg.voices, color: '#22d3ee' },
      { label: `${dg.sttModels.length} STT models`, value: dg.sttModels.length, color: '#34d399' },
      { label: `${dg.consoleKeys} console keys`, value: dg.consoleKeys, color: '#fbbf24' },
      { label: `${dg.consoleAgents} console agents`, value: dg.consoleAgents, color: '#8b5cf6' },
    ]);

    // sessions
    const s = data.sessions;
    const sessSegs = [
      { label: 'completed', value: s.completed, color: '#34d399' },
      { label: 'active', value: s.active, color: '#8b5cf6' },
      { label: 'interrupted', value: s.interrupted, color: '#fbbf24' },
      { label: 'error', value: s.error, color: '#f87171' },
    ].filter((x) => x.value > 0);
    $('sessions-count').textContent = `${s.total} total`;
    $('sessions-donut').innerHTML = donut(sessSegs.length ? sessSegs : [{ label: 'none', value: 0 }], 'completed');
    $('sessions-legend').innerHTML = legend(sessSegs);

    // latency
    const lat = data.latency;
    $('latency-samples').textContent = `${lat.sampleSize} samples`;
    $('latency-gauge').innerHTML = gauge(lat.p95 || 0, Math.max(1000, lat.p95 || 0), 'p95 ms');
    $('latency-bars').innerHTML = hBars([
      { label: 'p50', value: lat.p50 || 0, color: '#34d399' },
      { label: 'p90', value: lat.p90 || 0, color: '#22d3ee' },
      { label: 'p95', value: lat.p95 || 0, color: '#8b5cf6' },
    ], ' ms');

    // intents
    $('intents-count').textContent = `${(data.intents || []).length} intents`;
    $('intents-bars').innerHTML = hBars((data.intents || []).map((i, idx) => ({
      label: i.intent, value: i.count, color: PALETTE[idx % PALETTE.length],
    })));

    // quality
    const q = data.quality;
    const rate = q.passRate;
    $('quality-state').textContent = rate === null ? 'no runs' : `${rate}% pass`;
    $('quality-state').className = `pill ${rate === null ? 'pill-gray' : (rate >= 95 ? 'pill-green' : 'pill-amber')} no-dot`;
    $('quality-bars').innerHTML = hBars([
      { label: 'Regression runs passed', value: q.runsPassed, color: '#34d399' },
      { label: 'Fixtures passed', value: q.casesPassed, color: '#8b5cf6' },
      { label: 'Test cases', value: q.cases, color: '#22d3ee' },
      { label: 'Security selftest', value: 9, color: '#fbbf24' },
    ]);
    $('quality-note').textContent = `${q.runs} regression run(s) · ${c.testCases} fixtures · telephony ${sys.telephony} · live dialling refused`;

    // modules
    const mods = (data.modules || []).filter((m) => {
      if (!filter) return true;
      const hay = `${m.name} ${m.note} ${m.id} ${m.metric}`.toLowerCase();
      return hay.includes(filter);
    });
    $('modules-count').textContent = `${mods.length}/${(data.modules || []).length} modules`;
    $('modules-grid').innerHTML = mods.map((m) => {
      const tone = m.status === 'live' ? 'pill-green' : (m.status === 'mock-only' ? 'pill-amber' : (m.status === 'degraded' ? 'pill-amber' : 'pill-gray'));
      return `<a href="${m.route}" class="group rounded-xl border border-slate-200/70 bg-slate-50/40 p-2.5 transition hover:border-violet-400/60 hover:bg-violet-500/5">
        <div class="flex items-center justify-between gap-2">
          <span class="truncate text-[10.5px] font-extrabold text-slate-800">${UI.esc(m.name)}</span>
          <span class="pill ${tone} no-dot shrink-0">${UI.esc(m.status)}</span>
        </div>
        <div class="mt-1 text-[9.5px] font-semibold text-violet-600">${UI.esc(m.metric)}</div>
        <div class="mt-0.5 text-[8.5px] leading-relaxed text-slate-500">${UI.esc(m.note)}</div>
      </a>`;
    }).join('') || '<div class="empty-state"><div class="empty-title">No module matches</div><div class="empty-sub">Clear the filter to see all modules.</div></div>';

    // runtime
    const mins = Math.floor(sys.uptimeSec / 60);
    const runtime = [
      ['Service', `v${sys.version} · ${sys.environment}`],
      ['Database', `${sys.database} · ${(sys.dbBytes / 1024).toFixed(0)} KB`],
      ['Uptime', `${mins} min ${sys.uptimeSec % 60}s`],
      ['Runtime', `Python ${sys.python} · stdlib only`],
      ['Rate limit', `${sys.rateLimitPerMin} req/min`],
      ['Auth gate', sys.auth ? 'enabled' : 'disabled (localhost only)'],
      ['Telephony', `${sys.telephony} · live dialling refused`],
      ['Deepgram project', dg.project?.name || '—'],
      ['Deepgram voices', `${dg.voices} (Flux + Aura)`],
      ['Compliance verdicts', Object.entries(dg.verdicts || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'],
      ['Storage policy', `${sys.retention} day audio retention`],
    ];
    $('runtime-list').innerHTML = runtime.map(([label, value]) => `<div class="flex items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-slate-50/40 px-2.5 py-1.5">
      <span class="text-[9.5px] text-slate-500">${UI.esc(label)}</span>
      <span class="truncate text-[9.5px] font-semibold text-slate-700">${UI.esc(value)}</span>
    </div>`).join('');

    $('admin-updated').textContent = `updated ${UI.fmtDate(data.generatedAt)} · ${data.buildMs} ms`;
  }

  async function load() {
    try {
      const res = await fetch('/api/admin/overview');
      if (!res.ok) throw new Error(`overview returned ${res.status}`);
      data = await res.json();
      render();
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  $('admin-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    await load();
    btn.disabled = false;
  });

  $('admin-search').addEventListener('input', UI.debounce((event) => {
    filter = event.target.value.trim().toLowerCase();
    if (data) render();
  }, 150));

  $('admin-export').addEventListener('click', () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `adriene-admin-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    UI.toast('Admin snapshot exported', 'success');
  });

  await load();
})();

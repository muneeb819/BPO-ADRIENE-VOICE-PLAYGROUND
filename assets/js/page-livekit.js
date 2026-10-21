/* LiveKit Cloud console for BPO Nexus.
   Sections mirror the LiveKit Cloud console: Overview, Sessions, Simulations,
   Agents, Voices, Telephony, Egress & Ingress, Usage, Settings — plus a live
   "Test the bot" panel that joins a room with the deployed agent. */
'use strict';

(async function initLivekit() {
  await Shell.mount('livekit');

  const $ = (id) => document.getElementById(id);
  let console_ = null;
  let section = 'overview';
  let room = null;      // livekit Room
  let testState = 'idle';

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '12 — LiveKit Cloud',
    title: 'LiveKit Cloud',
    sub: 'Access, control, use, build and deploy LiveKit voice agents: the console sections, your cloud agents and a live bot test from this browser.',
    right: `<a class="btn btn-outline" href="/deepgram">${Shell.icon('bolt')} Deepgram</a>
      <a class="btn btn-primary" href="/admin">${Shell.icon('grid')} Admin Panel</a>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  // --- helpers ------------------------------------------------------------
  function stat(label, value, sub) {
    return `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
      <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">${UI.esc(label)}</div>
      <div class="mt-1 font-mono text-[18px] font-bold text-slate-800">${UI.esc(String(value))}</div>
      ${sub ? `<div class="mt-0.5 text-[8.5px] text-slate-500">${UI.esc(sub)}</div>` : ''}
    </div>`;
  }

  function empty(text) {
    return `<div class="rounded-lg border border-dashed border-slate-300 bg-slate-50/50 px-3 py-4 text-center text-[10px] text-slate-500">${UI.esc(text)}</div>`;
  }

  function agentCard(agent) {
    const deployments = (agent.deployments || []).map((d) => `<span class="chip">${UI.esc(d.region || '-')} · ${UI.esc(d.status || '-')}</span>`).join(' ');
    return `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="truncate text-[10.5px] font-extrabold text-slate-800">${UI.esc(agent.name || agent.id)}</span>
        <span class="chip chip-mono">v${UI.esc(agent.version || '-')}</span>
      </div>
      <div class="mono mt-0.5 truncate text-[8px] text-slate-400">${UI.esc(agent.id || '')}</div>
      <div class="mt-1.5 flex flex-wrap gap-1.5">${deployments}</div>
      <div class="mt-2 flex flex-wrap gap-1.5">
        <button class="btn btn-xs btn-outline" data-versions="${UI.esc(agent.id || '')}" type="button">Versions</button>
        <button class="btn btn-xs btn-soft" data-secrets="${UI.esc(agent.id || '')}" type="button">Secrets</button>
        <button class="btn btn-xs btn-soft" data-simulate="${UI.esc(agent.name || '')}" type="button">Simulate</button>
      </div>
      <div class="mt-2 hidden space-y-1" id="cloud-detail-${UI.esc(agent.id || '')}"></div>
    </div>`;
  }

  function wireDetailButtons(root) {
    root.querySelectorAll('[data-versions]').forEach((btn) => {
      btn.addEventListener('click', () => showCloudDetail(btn.dataset.versions, 'versions'));
    });
    root.querySelectorAll('[data-secrets]').forEach((btn) => {
      btn.addEventListener('click', () => showCloudDetail(btn.dataset.secrets, 'secrets'));
    });
    root.querySelectorAll('[data-simulate]').forEach((btn) => {
      btn.addEventListener('click', () => runSimulation(btn.dataset.simulate));
    });
  }

  async function showCloudDetail(agentId, kind) {
    const target = document.getElementById(`cloud-detail-${agentId}`);
    if (!target) return;
    if (!target.classList.contains('hidden')) {
      target.classList.add('hidden');
      return;
    }
    target.classList.remove('hidden');
    target.innerHTML = '<div class="text-[9px] text-slate-400">Loading…</div>';
    try {
      const res = await fetch(`/api/livekit/cloud/agents/${encodeURIComponent(agentId)}/${kind}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'request failed');
      if (kind === 'versions') {
        const versions = data.versions || [];
        target.innerHTML = versions.length
          ? versions.map((v) => `<div class="rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
              <div class="flex items-center justify-between gap-2">
                <span class="mono text-[9px] font-semibold text-slate-700">${UI.esc(v.version)}</span>
                ${v.current ? '<span class="pill pill-green no-dot">current</span>' : ''}
              </div>
              <div class="mt-0.5 text-[8px] text-slate-500">${UI.esc(v.status || '')}${v.active ? ' · active' : ''} · created ${UI.esc(String(v.createdAt).slice(0, 10))}</div>
            </div>`).join('')
          : '<div class="text-[9px] text-slate-400">No versions.</div>';
      } else {
        const secrets = data.secrets || [];
        target.innerHTML = secrets.length
          ? secrets.map((s) => `<div class="rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
              <div class="text-[9px] font-semibold text-slate-700">${UI.esc(s.name)}</div>
              <div class="mt-0.5 text-[8px] text-slate-500">${UI.esc(s.kind || 'environment')} · value hidden</div>
            </div>`).join('')
          : '<div class="text-[9px] text-slate-400">No secrets.</div>';
      }
    } catch (err) {
      target.innerHTML = `<div class="text-[9px] text-red-400">${UI.esc(err.message)}</div>`;
    }
  }

  async function runSimulation(agentName) {
    const body = $('lk-section-body');
    body.innerHTML = '<div class="text-[10px] text-slate-400">Running judged simulations on LiveKit Cloud — this can take a minute…</div>';
    try {
      const res = await fetch('/api/livekit/console/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agentName, scenarios: 2 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'simulation failed');
      await loadConsole();
      renderSection();
    } catch (err) {
      body.innerHTML = `<div class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[9.5px] text-red-700">${UI.esc(err.message)}</div>`;
    }
  }

  // --- sections -----------------------------------------------------------
  const SECTIONS = {
    overview: {
      title: 'Overview',
      sub: 'Project, agents, deployments and live rooms.',
      render(c) {
        const u = c.usage || {};
        return `<div class="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            ${stat('Agents', u.agents || 0, 'in LiveKit Cloud')}
            ${stat('Deployments', u.deployments || 0, 'regions running the agent')}
            ${stat('Live rooms', u.rooms || 0, 'right now')}
            ${stat('Participants', u.participants || 0, 'connected callers')}
          </div>
          <div class="mt-3 grid gap-3 lg:grid-cols-2">
            <div>
              <div class="label">Agents</div>
              <div class="space-y-2">${(c.agents || []).map(agentCard).join('') || empty('No cloud agents visible.')}</div>
            </div>
            <div>
              <div class="label">Live rooms</div>
              <div class="space-y-2">${(c.rooms || []).map((r) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
                  <div class="flex items-center justify-between gap-2">
                    <span class="truncate text-[10.5px] font-extrabold text-slate-800">${UI.esc(r.name)}</span>
                    <span class="chip chip-mono">${r.participants} in</span>
                  </div>
                  <div class="mt-1 flex flex-wrap gap-1.5 text-[8.5px] text-slate-500">
                    ${(r.dispatches || []).map((d) => `<span class="chip">agent ${UI.esc(d.agentName)}</span>`).join('')}
                  </div>
                </div>`).join('') || empty('No live rooms. Create one from “Test the bot”.')}</div>
            </div>
          </div>`;
      },
    },
    sessions: {
      title: 'Sessions',
      sub: 'Live rooms, their participants and the agents dispatched into them.',
      render(c) {
        return `<div class="space-y-2">${(c.rooms || []).map((r) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="truncate text-[10.5px] font-extrabold text-slate-800">${UI.esc(r.name)}</span>
              <span class="chip chip-mono">${r.participants} participant(s)</span>
            </div>
            <div class="mt-1.5 grid gap-1 sm:grid-cols-2">
              <div>
                <div class="text-[8px] font-extrabold uppercase tracking-[0.1em] text-slate-500">Participants</div>
                <div class="mt-1 space-y-1">
                  ${(r.participantList || []).map((p) => `<div class="flex items-center justify-between gap-2 text-[9px] text-slate-600">
                    <span class="truncate">${UI.esc(p.name || p.identity)}${p.isAgent ? ' · agent' : ''}</span>
                    <span class="chip">${UI.esc(p.state || '')}</span>
                  </div>`).join('') || '<div class="text-[9px] text-slate-400">Nobody in the room.</div>'}
                </div>
              </div>
              <div>
                <div class="text-[8px] font-extrabold uppercase tracking-[0.1em] text-slate-500">Dispatches</div>
                <div class="mt-1 space-y-1">
                  ${(r.dispatches || []).map((d) => `<div class="flex items-center justify-between gap-2 text-[9px] text-slate-600">
                    <span class="truncate">${UI.esc(d.agentName || d.id)}</span>
                    <span class="chip">running</span>
                  </div>`).join('') || '<div class="text-[9px] text-slate-400">No agent dispatched.</div>'}
                </div>
              </div>
            </div>
          </div>`).join('') || empty('No sessions yet — create a room and dispatch the agent from “Test the bot”.')}</div>`;
      },
    },
    simulations: {
      title: 'Simulations',
      sub: 'Judged simulations of the deployed agent, run on LiveKit Cloud.',
      render(c) {
        return `<div class="flex flex-wrap items-center gap-2">
            <button class="btn btn-outline btn-xs" id="lk-sim-run" type="button"><span data-icon="play"></span> Run text simulation</button>
            <span class="text-[9px] text-slate-500">Runs against the registered agent on LiveKit Cloud and reports pass/fail per scenario.</span>
          </div>
          <div class="mt-3 space-y-2">
            ${(c.simulations || []).map((s) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <span class="mono text-[9.5px] font-semibold text-slate-700">${UI.esc(s.id || s.agentName || 'run')}</span>
                  <span class="chip">${UI.esc(s.status || 'unknown')}</span>
                </div>
                <div class="mt-1 text-[8.5px] text-slate-500">${UI.esc(s.agentName || '')} · ${s.numSimulations || 0} scenario(s) · ${s.passed || 0} passed / ${s.failed || 0} failed · ${UI.esc(String(s.createdAt).slice(0, 19))}</div>
              </div>`).join('') || empty('No simulation runs yet.')}`;
      },
    },
    agents: {
      title: 'Agents',
      sub: 'Agents created in the LiveKit Cloud console, with versions and secrets.',
      render(c) {
        return `<div class="grid gap-2.5 sm:grid-cols-2">
            ${(c.agents || []).map(agentCard).join('') || empty('No cloud agents visible for this key.')}
          </div>`;
      },
    },
    voices: {
      title: 'Voices',
      sub: 'The voice catalogue available to your agents.',
      render(c) {
        const voices = window.VOICE_CATALOG ? window.VOICE_CATALOG.all : [];
        return `<div class="grid gap-2.5 sm:grid-cols-3">
            ${stat('TTS voices', c.voices?.ttsVoices || voices.length, 'Deepgram Flux + Aura')}
            ${stat('Families', (c.voices?.families || ['Flux', 'Aura']).join(' + '), 'LiveKit Inference + Deepgram')}
            ${stat('Default dispatch', c.project?.agentName || '—', 'agent used by Test the bot')}
          </div>
          <div class="mt-3 max-h-[320px] overflow-y-auto pr-1">
            <div class="grid gap-1 sm:grid-cols-2">
              ${voices.map((v) => `<div class="flex items-center justify-between gap-2 rounded-lg border border-slate-200/60 bg-white/40 px-2 py-1.5">
                <span class="truncate text-[9.5px] text-slate-700">${UI.esc(v.family)} · ${UI.esc(v.name)}</span>
                <span class="text-[8.5px] text-slate-500">${UI.esc(v.accent)}, ${UI.esc(v.gender)}</span>
              </div>`).join('')}
            </div>
          </div>`;
      },
    },
    telephony: {
      title: 'Telephony',
      sub: 'SIP trunks, dispatch rules and participants.',
      render(c) {
        const t = c.telephony || {};
        const rows = [
          ['Inbound trunks', (t.inbound || []).length],
          ['Outbound trunks', (t.outbound || []).length],
          ['Dispatch rules', (t.dispatchRules || []).length],
          ['SIP participants', (t.participants || []).length],
        ];
        return `<div class="grid gap-2.5 sm:grid-cols-4">
            ${rows.map(([label, value]) => stat(label, value, 'LiveKit Cloud')).join('')}
          </div>
          <div class="mt-3 space-y-2">
            ${(t.inbound || []).concat(t.outbound || []).map((trunk) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3 text-[9.5px] text-slate-700">
              <div class="font-semibold">${UI.esc(trunk.name || trunk.trunk_id || 'trunk')}</div>
              <div class="mt-0.5 text-[8.5px] text-slate-500">${UI.esc(JSON.stringify(trunk).slice(0, 220))}</div>
            </div>`).join('')}
          </div>
          <p class="mt-3 text-[9px] leading-relaxed text-slate-500">Telephony in this build stays mock-only: the BPO Nexus app refuses live dialling on purpose, so trunks and dispatch rules are read-only here.</p>`;
      },
    },
    media: {
      title: 'Egress & Ingress',
      sub: 'Recording/streaming jobs and external media ingress.',
      render(c) {
        const m = c.media || {};
        return `<div class="grid gap-2.5 sm:grid-cols-2">
            ${stat('Egress jobs', (m.egress || []).length, 'recording / streaming')}
            ${stat('Ingress endpoints', (m.ingress || []).length, 'external media in')}
          </div>
          <div class="mt-3 space-y-2">
            ${(m.egress || []).map((job) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3 text-[9.5px] text-slate-700">
              <div class="font-semibold">${UI.esc(job.egress_id || job.room_name || 'egress')}</div>
              <div class="mt-0.5 text-[8.5px] text-slate-500">${UI.esc(JSON.stringify(job).slice(0, 220))}</div>
            </div>`).join('')}
            ${(m.ingress || []).map((job) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3 text-[9.5px] text-slate-700">
              <div class="font-semibold">${UI.esc(job.ingress_id || job.name || 'ingress')}</div>
              <div class="mt-0.5 text-[8.5px] text-slate-500">${UI.esc(JSON.stringify(job).slice(0, 220))}</div>
            </div>`).join('')}
            ${(!(m.egress || []).length && !(m.ingress || []).length) ? empty('No active egress or ingress jobs.') : ''}
          </div>`;
      },
    },
    usage: {
      title: 'Usage',
      sub: 'What the platform is doing right now.',
      render(c) {
        const u = c.usage || {};
        return `<div class="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            ${stat('Rooms', u.rooms || 0, 'live now')}
            ${stat('Participants', u.participants || 0, 'in rooms')}
            ${stat('Agents', u.agents || 0, 'in the cloud')}
            ${stat('Simulations', u.simulations || 0, 'runs recorded')}
          </div>
          <div class="mt-3 rounded-xl border border-slate-200/70 bg-slate-50/40 p-3 text-[9.5px] text-slate-600">
            Session-level usage for the BPO Nexus side (turns, latency percentiles, intent mix) lives in
            <a class="font-semibold text-violet-600 underline" href="/analytics">Analytics</a>.
          </div>`;
      },
    },
    settings: {
      title: 'Settings',
      sub: 'Projects, credentials and deployment commands.',
      render(c) {
        const p = c.project || {};
        return `<div class="grid gap-2.5 sm:grid-cols-2">
            <div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
              <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Project</div>
              <div class="mt-1.5 space-y-1 text-[9.5px] text-slate-700">
                <div>URL <span class="mono">${UI.esc(p.url || '-')}</span></div>
                <div>Agent dispatch <span class="mono">${UI.esc(p.agentName || '-')}</span></div>
                <div>Project key ${p.hasProjectKey ? '<span class="pill pill-green no-dot">configured</span>' : '<span class="pill pill-red no-dot">missing</span>'}</div>
                <div>Cloud key ${p.hasCloudKey ? '<span class="pill pill-green no-dot">configured</span>' : '<span class="pill pill-amber no-dot">missing</span>'}</div>
              </div>
            </div>
            <div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
              <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Configured projects</div>
              <div class="mt-1.5 space-y-1">
                ${(p.projects || []).map((proj) => `<div class="flex items-center justify-between gap-2 text-[9.5px] text-slate-700">
                  <span class="truncate">${UI.esc(proj.name || proj.projectId)}</span>
                  <span class="chip chip-mono">${UI.esc(proj.apiKey || '••••')}</span>
                </div>`).join('') || '<div class="text-[9px] text-slate-400">No projects in the CLI config.</div>'}
              </div>
              <p class="mt-2 text-[8.5px] leading-relaxed text-slate-500">Secret values are never read or returned — only key prefixes and project names.</p>
            </div>
          </div>
          <div class="mt-3 rounded-xl border border-slate-200/70 bg-slate-50/40 p-3">
            <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Deploy</div>
            <p class="mt-1.5 text-[9.5px] leading-relaxed text-slate-600">
              Generate a worker from the builder below, then deploy it with the official CLI:
            </p>
            <pre class="mono mt-2 overflow-auto rounded-lg border border-slate-200/70 bg-white/60 p-2.5 text-[8.5px] leading-relaxed text-slate-600">lk agent deploy --url ${UI.esc(p.url || '')} --agent ${UI.esc(p.agentName || '')}</pre>
          </div>`;
      },
    },
  };

  function renderSection() {
    const view = SECTIONS[section] || SECTIONS.overview;
    $('lk-section-title').textContent = view.title;
    $('lk-section-sub').textContent = view.sub;
    const body = $('lk-section-body');
    if (!console_) {
      body.innerHTML = '<div class="text-[10px] text-slate-400">Loading the console…</div>';
      return;
    }
    body.innerHTML = view.render(console_);
    wireDetailButtons(body);
    const run = body.querySelector('#lk-sim-run');
    if (run) {
      run.addEventListener('click', () => runSimulation(console_.project?.agentName || ''));
    }
    $('lk-section-stamp').textContent = `updated ${UI.fmtDate(console_.generatedAt)}`;
  }

  async function loadConsole() {
    try {
      const res = await fetch('/api/livekit/console');
      console_ = await res.json();
      if (!res.ok) throw new Error(console_.error || 'console failed');
    } catch (err) {
      console_ = null;
      $('lk-section-body').innerHTML = `<div class="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[9.5px] text-red-700">${UI.esc(err.message)}</div>`;
      return;
    }
    renderSection();
  }

  // --- test the bot -------------------------------------------------------
  function setTestState(state, detail) {
    testState = state;
    const pill = $('lk-test-state');
    pill.textContent = detail || state;
    pill.className = `pill ${state === 'connected' ? 'pill-green-dark' : (state === 'error' ? 'pill-red-dark' : 'pill-dark')}`;
  }

  function showError(message) {
    const box = $('lk-test-error');
    if (!message) {
      box.classList.add('hidden');
      box.textContent = '';
      return;
    }
    box.classList.remove('hidden');
    box.textContent = message;
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
    return data;
  }

  $('lk-test-create').addEventListener('click', async () => {
    showError('');
    const name = $('lk-test-room').value.trim() || 'adriene-bot-test';
    try {
      await api('/api/livekit/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      setTestState('room created', `${name} ready`);
      await loadConsole();
    } catch (err) {
      setTestState('error');
      showError(err.message);
    }
  });

  $('lk-test-dispatch').addEventListener('click', async () => {
    showError('');
    const name = $('lk-test-room').value.trim() || 'adriene-bot-test';
    // Prefer the agent that actually exists in LiveKit Cloud.
    const cloudAgent = (console_?.agents || [])[0];
    const agentName = cloudAgent?.name || console_?.project?.agentName || '';
    try {
      const data = await api('/api/livekit/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room: name, agentName }),
      });
      setTestState('agent dispatched', `${data.agentName} → ${data.room}`);
      await loadConsole();
    } catch (err) {
      setTestState('error');
      showError(err.message);
    }
  });

  $('lk-test-join').addEventListener('click', async () => {
    showError('');
    const name = $('lk-test-room').value.trim() || 'adriene-bot-test';
    if (!window.LivekitClient) {
      setTestState('error');
      showError('The LiveKit browser client failed to load.');
      return;
    }
    try {
      setTestState('connecting…', 'joining room');
      const token = await api('/api/livekit/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room: name, identity: `operator-${Math.random().toString(36).slice(2, 8)}` }),
      });
      const { Room, RoomEvent, Track } = window.LivekitClient;
      room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });
      room.on(RoomEvent.TranscriptionReceived, (transcription, participant) => {
        appendTranscript(participant?.identity || 'bot', transcription?.text || '');
      });
      room.on(RoomEvent.ParticipantConnected, (p) => {
        appendTranscript('system', `${p.identity} joined`);
        renderParticipants();
      });
      room.on(RoomEvent.ParticipantDisconnected, (p) => {
        appendTranscript('system', `${p.identity} left`);
        renderParticipants();
      });
      room.on(RoomEvent.TrackSubscribed, async (track) => {
        if (track.kind === Track.Kind.Audio) {
          try {
            const attached = track.attach();
            const el = attached && typeof attached.then === 'function' ? await attached : attached;
            if (el) {
              el.className = 'lk-audio';
              el.style.display = 'none';
              const host = document.getElementById('lk-test-audio-host');
              if (host) host.appendChild(el);
            }
          } catch (err) {
            appendTranscript('system', `audio attach failed: ${err.message}`);
          }
        }
      });
      await room.connect(token.url, token.token);
      await room.localParticipant.setMicrophoneEnabled(true);
      setTestState('connected', `live in ${name}`);
      $('lk-test-leave').disabled = false;
      renderParticipants();
      appendTranscript('system', `you joined ${name} with the microphone live`);
      loadConsole();
    } catch (err) {
      setTestState('error');
      const denied = /permission|not allowed|denied/i.test(err.message || '');
      showError(denied
        ? 'Microphone permission was denied. Allow the microphone for this site in the browser (the padlock icon) and join again.'
        : `${err.message}. Microphone capture needs a secure context — use https://${location.hostname} or http://localhost.`);
    }
  });

  $('lk-test-leave').addEventListener('click', async () => {
    try {
      if (room) await room.disconnect();
    } catch { /* ignore */ }
    room = null;
    $('lk-test-leave').disabled = true;
    setTestState('idle', 'left the room');
    renderParticipants();
    await loadConsole();
  });

  function appendTranscript(who, text) {
    const box = $('lk-test-transcript');
    if (!box) return;
    if (box.querySelector('.placeholder-note')) box.innerHTML = '';
    const line = document.createElement('div');
    line.className = 'flex items-start gap-2 text-[9.5px]';
    line.innerHTML = `<span class="mono w-[72px] shrink-0 text-teal-400">${UI.esc(who)}</span><span class="text-slate-300">${UI.esc(text)}</span>`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function renderParticipants() {
    const box = $('lk-test-participants');
    if (!box) return;
    if (!room) {
      box.innerHTML = '<div class="text-slate-500">Not connected.</div>';
      return;
    }
    const people = [...room.remoteParticipants.values()].map((p) => ({
      identity: p.identity,
      state: p.isSpeaking ? 'speaking' : 'connected',
    }));
    people.push({ identity: room.localParticipant.identity, state: 'you (mic on)' });
    box.innerHTML = people.map((p) => `<div class="flex items-center justify-between gap-2">
        <span class="truncate">${UI.esc(p.identity)}</span><span class="chip">${UI.esc(p.state)}</span>
      </div>`).join('') || '<div class="text-slate-500">Nobody else in the room.</div>';
  }

  // --- rail + refresh -----------------------------------------------------
  $('lk-rail').addEventListener('click', (event) => {
    const item = event.target.closest('[data-section]');
    if (!item) return;
    section = item.dataset.section;
    $('lk-rail').querySelectorAll('.lk-rail-item').forEach((btn) => {
      btn.classList.toggle('active', btn === item);
    });
    renderSection();
  });

  $('lk-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    await loadConsole();
    btn.disabled = false;
  });

  await loadConsole();
})();

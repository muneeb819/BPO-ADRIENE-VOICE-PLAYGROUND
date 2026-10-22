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
  let voices = [];          // voice catalogue from the server
  let voiceInUse = {};      // voice id -> [agent names]
  let voiceQuery = '';
  let voiceFamily = 'all';
  let selectedVoice = null;
  let voiceTargetAgent = '';
  let agents = [];
  let builder = null;       // saved Agent Builder config
  let builderFiles = null;  // generated worker files
  let audio = null;         // preview player
  const DEFAULT_SCENARIOS = [
    'Introduce yourself and ask whether now is a good time to talk. || The agent identifies itself, states the campaign purpose and asks permission to continue.',
    'Say you are between 45 and 85 years old. || The agent confirms the age range and asks the next screening question in order.',
    'Say you are not interested. || The agent acknowledges politely, ends the call and does not push further.',
  ];
  let simScenarios = DEFAULT_SCENARIOS.join('\n');

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

  let simPoll = null;

  function pollSimulation() {
    if (simPoll) clearInterval(simPoll);
    let ticks = 0;
    simPoll = setInterval(async () => {
      ticks += 1;
      await loadConsole();
      if (section === 'simulations') renderSection();
      const live = console_ && console_.lastSimulation;
      if (!live || live.status !== 'running' || ticks > 60) {
        clearInterval(simPoll);
        simPoll = null;
      }
    }, 10000);
  }

  async function runSimulation(agentName) {    const body = $('lk-section-body');
    const field = document.getElementById('lk-sim-scenarios');
    const scenarios = (field ? field.value : '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 10);
    body.innerHTML = '<div class="text-[10px] text-slate-400">Starting judged simulation on LiveKit Cloud — this can take a minute…</div>';
    try {
      const res = await fetch('/api/livekit/console/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agentName, scenarios: scenarios.length ? scenarios : 2 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'simulation failed');
      await loadConsole();
      renderSection();
      pollSimulation();
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
        const live = c.lastSimulation || {};
        const liveBanner = live.status && live.status !== 'idle'
          ? `<div class="mt-2 rounded-lg border px-3 py-2 text-[9.5px] ${
              live.status === 'running'
                ? 'border-sky-500/30 bg-sky-500/10 text-sky-700'
                : live.status === 'completed'
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700'
                  : 'border-red-500/30 bg-red-500/10 text-red-700'}">
              <span class="font-semibold">Last run: ${UI.esc(live.status)}</span>
              ${live.agentName ? ` · ${UI.esc(live.agentName)}` : ''}
              ${live.outcome ? `<div class="mt-1 whitespace-pre-wrap">${UI.esc(live.outcome)}</div>` : ''}
              ${live.startedAt ? `<div class="mt-1 text-[8.5px] opacity-70">started ${UI.esc(String(live.startedAt).slice(0, 19))}</div>` : ''}
            </div>`
          : '';
        return `<div class="flex flex-wrap items-center gap-2">
            <button class="btn btn-outline btn-xs" id="lk-sim-run" type="button"><span data-icon="play"></span> Run text simulation</button>
            <span class="text-[9px] text-slate-500">Runs against the registered agent on LiveKit Cloud and reports pass/fail per scenario.</span>
          </div>
          <div class="mt-2">
            <label class="label" for="lk-sim-scenarios">Scenarios (one per line)</label>
            <textarea class="textarea input-sm" id="lk-sim-scenarios" rows="4">${UI.esc(simScenarios)}</textarea>
            <p class="mt-1 text-[8.5px] text-slate-500">One judged scenario per line: <span class="mono">what the caller says || what the agent must do to pass</span>. Leave the second part out to use the default expectation.</p>
          </div>
          ${liveBanner}
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
      sub: 'Search, preview, bind to the Agent Builder or save straight to an agent.',
      render(c) {
        const catalogue = window.VOICE_CATALOG ? window.VOICE_CATALOG.all : [];
        const list = catalogue.filter((v) => {
          if (voiceFamily !== 'all' && v.family !== voiceFamily) return false;
          if (!voiceQuery) return true;
          const hay = `${v.family} ${v.name} ${v.accent} ${v.gender} ${v.id}`.toLowerCase();
          return hay.includes(voiceQuery);
        });
        const inUse = voiceInUse || {};
        const usedCount = Object.keys(inUse).filter((k) => k).length;
        return `<div class="grid gap-2.5 sm:grid-cols-4">
            ${stat('TTS voices', c.voices?.ttsVoices || catalogue.length, 'Deepgram Flux + Aura')}
            ${stat('Families', (c.voices?.families || ['Flux', 'Aura']).join(' + '), 'LiveKit Inference + Deepgram')}
            ${stat('In use', usedCount, 'voices bound to agents')}
            ${stat('Default dispatch', c.project?.agentName || '—', 'agent used by Test the bot')}
          </div>

          <div class="mt-3 flex flex-wrap items-center gap-2">
            <input class="input input-sm min-w-[180px] flex-1" id="lk-voice-search" placeholder="Search name, accent, gender or model id" value="${UI.esc(voiceQuery)}" aria-label="Search voices" />
            ${['all', 'Flux', 'Aura'].map((f) => `<button class="btn btn-xs ${voiceFamily === f ? 'btn-primary' : 'btn-outline'}" data-family="${f}" type="button">${f === 'all' ? 'All' : f}</button>`).join('')}
          </div>

          <div class="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
            <select class="select input-sm" id="lk-voice-target" aria-label="Target agent">
              <option value="">Select an agent to save the voice to…</option>
              ${agents.map((a) => `<option value="${UI.esc(a.id)}" ${voiceTargetAgent === a.id ? 'selected' : ''}>${UI.esc(a.name)} — ${UI.esc(a.voice || 'no voice')}</option>`).join('')}
            </select>
            <button class="btn btn-outline btn-xs" id="lk-voice-save" type="button" ${selectedVoice ? '' : 'disabled'}>
              <span data-icon="save"></span> Save voice to agent
            </button>
          </div>

          <div class="mt-3 max-h-[340px] space-y-1 overflow-y-auto pr-1">
            ${list.length ? list.map((v) => {
              const used = inUse[v.id] || [];
              const active = selectedVoice === v.id;
              return `<div data-select-voice="${UI.esc(v.id)}" class="flex cursor-pointer flex-wrap items-center justify-between gap-2 rounded-lg border px-2 py-1.5 ${active ? 'border-violet-400 bg-violet-50' : 'border-slate-200/60 bg-white/40'}">
                <div class="min-w-0">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate text-[9.5px] font-semibold text-slate-700">${UI.esc(v.family)} · ${UI.esc(v.name)}</span>
                    ${used.length ? `<span class="chip">in use: ${used.map((n) => UI.esc(n)).join(', ')}</span>` : ''}
                  </div>
                  <div class="text-[8.5px] text-slate-500">${UI.esc(v.accent)}, ${UI.esc(v.gender)} · ${UI.esc(v.id)}</div>
                </div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <button class="btn btn-xs btn-soft" data-preview="${UI.esc(v.id)}" type="button">▶ Preview</button>
                  <button class="btn btn-xs btn-outline" data-use-voice="${UI.esc(v.id)}" type="button">Use in builder</button>
                </div>
              </div>`;
            }).join('') : '<div class="rounded-lg border border-dashed border-slate-300 px-3 py-6 text-center text-[10px] text-slate-500">No voice matches that filter.</div>'}
          </div>
          <p class="mt-2 text-[9px] text-slate-500">Preview synthesizes the voice with the real Deepgram key. "Use in builder" binds it to the Agent Builder's TTS voice.</p>`;
      },
    },
    builder: {
      title: 'Agent Builder',
      sub: 'Configure the agent, generate the worker and deploy it to LiveKit Cloud.',
      render() {
        const b = builder || {};
        const catalogue = window.VOICE_CATALOG ? window.VOICE_CATALOG.all : [];
        const cloudAgents = (console_?.agents || []);
        return `<div class="grid gap-3 lg:grid-cols-2">
            <div class="space-y-2.5">
              <div class="grid gap-2.5 sm:grid-cols-2">
                <div>
                  <label class="label" for="lb-name">Agent name</label>
                  <input class="input input-sm" id="lb-name" value="${UI.esc(b.name || '')}" />
                </div>
                <div>
                  <label class="label" for="lb-agent">Deploy target (cloud agent)</label>
                  <select class="select input-sm" id="lb-agent">
                    <option value="">— new agent —</option>
                    ${cloudAgents.map((a) => `<option value="${UI.esc(a.id)}" ${b.agentId === a.id ? 'selected' : ''}>${UI.esc(a.name)} (${UI.esc(a.id)})</option>`).join('')}
                  </select>
                </div>
                <div>
                  <label class="label" for="lb-stt">STT model</label>
                  <input class="input input-sm" id="lb-stt" value="${UI.esc(b.sttModel || 'xai/stt-1')}" />
                </div>
                <div>
                  <label class="label" for="lb-llm">LLM model</label>
                  <input class="input input-sm" id="lb-llm" value="${UI.esc(b.llmModel || 'google/gemma-4-31b-it')}" />
                </div>
                <div>
                  <label class="label" for="lb-tts">TTS model</label>
                  <input class="input input-sm" id="lb-tts" value="${UI.esc(b.ttsModel || 'fishaudio/s2.1-pro')}" />
                </div>
                <div>
                  <label class="label" for="lb-voice">TTS voice</label>
                  <select class="select input-sm" id="lb-voice">
                    ${catalogue.map((v) => `<option value="${UI.esc(v.id)}" ${b.ttsVoice === v.id ? 'selected' : ''}>${UI.esc(v.family)} - ${UI.esc(v.name)} (${UI.esc(v.accent)}, ${UI.esc(v.gender)})</option>`).join('')}
                  </select>
                </div>
              </div>
              <div>
                <label class="label" for="lb-greeting">Greeting (Optional)</label>
                <textarea class="textarea input-sm" id="lb-greeting" rows="2" maxlength="500">${UI.esc(b.greeting || '')}</textarea>
              </div>
              <div>
                <label class="label" for="lb-prompt">Agent prompt</label>
                <textarea class="textarea input-sm" id="lb-prompt" rows="7" maxlength="8000">${UI.esc(b.prompt || '')}</textarea>
              </div>
              <div class="flex flex-wrap items-center gap-3">
                <label class="flex items-center gap-2 text-[10px] text-slate-600"><input type="checkbox" class="checkbox" id="lb-interrupt" ${b.interruption !== false ? 'checked' : ''} /> Interruption</label>
                <label class="flex items-center gap-2 text-[10px] text-slate-600"><input type="checkbox" class="checkbox" id="lb-preemptive" ${b.preemptive !== false ? 'checked' : ''} /> Preemptive generation</label>
                <select class="select input-sm w-auto" id="lb-turn">
                  ${['vad', 'stt', 'manual'].map((t) => `<option value="${t}" ${b.turnDetection === t ? 'selected' : ''}>turn detection: ${t}</option>`).join('')}
                </select>
              </div>
            </div>
            <div class="space-y-2.5">
              <div class="flex flex-wrap items-center gap-2">
                <button class="btn btn-primary btn-xs" id="lb-generate" type="button"><span data-icon="code"></span> Generate worker</button>
                <button class="btn btn-outline btn-xs" id="lb-zip" type="button"><span data-icon="download"></span> Download ZIP</button>
                <button class="btn btn-outline btn-xs" id="lb-deploy" type="button"><span data-icon="upload"></span> Deploy to LiveKit</button>
                <span class="text-[9px] text-slate-500" id="lb-status">${builderFiles ? 'worker generated' : 'not generated yet'}</span>
              </div>
              <div class="flex flex-wrap gap-1.5" id="lb-file-tabs"></div>
              <pre class="mono max-h-[420px] overflow-auto rounded-xl border border-slate-200/70 bg-slate-50/50 p-3 text-[8.5px] leading-relaxed text-slate-600" id="lb-code">Generate the worker to preview the code that will be deployed.</pre>
              <div class="hidden rounded-lg border border-slate-200/70 bg-slate-50/50 p-2.5 text-[9px] leading-relaxed text-slate-600" id="lb-output"></div>
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
    wireSection(body);
    if (section === 'builder') renderBuilderFiles();
    const run = body.querySelector('#lk-sim-run');
    if (run) {
      run.addEventListener('click', () => runSimulation(
        (console_?.agents || [])[0]?.name || console_?.project?.agentName || ''));
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

  // --- voices ------------------------------------------------------------
  async function loadVoices() {
    try {
      const res = await fetch('/api/livekit/voices');
      const data = await res.json();
      voiceInUse = data.inUse || {};
    } catch { /* keep empty */ }
  }

  async function loadAgents() {
    try {
      agents = await API.agents();
    } catch { agents = []; }
  }

  async function loadBuilder() {
    try {
      const res = await fetch('/api/livekit/builder');
      builder = await res.json();
    } catch { builder = null; }
  }

  function builderFromForm() {
    const get = (id) => document.getElementById(id);
    if (!get('lb-name')) return null;   // builder panel is not rendered
    return {
      name: get('lb-name')?.value.trim() || 'Agent',
      agentId: get('lb-agent')?.value || '',
      sttModel: get('lb-stt')?.value.trim() || 'xai/stt-1',
      llmModel: get('lb-llm')?.value.trim() || 'google/gemma-4-31b-it',
      ttsModel: get('lb-tts')?.value.trim() || 'fishaudio/s2.1-pro',
      ttsVoice: get('lb-voice')?.value || 'flux-brittany-en',
      greeting: get('lb-greeting')?.value.trim() || '',
      prompt: get('lb-prompt')?.value || '',
      interruption: get('lb-interrupt')?.checked !== false,
      preemptive: get('lb-preemptive')?.checked !== false,
      turnDetection: get('lb-turn')?.value || 'vad',
    };
  }

  async function saveBuilder(silent) {
    if (!builder) return;
    const fromForm = builderFromForm();
    if (fromForm) builder = fromForm;
    try {
      await fetch('/api/livekit/builder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(builder),
      });
      if (!silent) {
        const status = document.getElementById('lb-status');
        if (status) status.textContent = 'saved';
      }
    } catch { /* ignore */ }
  }

  async function previewVoice(voiceId) {
    const name = voiceId.split('-').slice(1, -1).join(' ') || voiceId;
    try {
      if (audio) { audio.pause(); }
      const blob = await API.tts(`Hi, this is ${name}. This is how I sound.`, voiceId);
      audio = new Audio(URL.createObjectURL(blob));
      await audio.play();
      UI.toast(`Playing ${name}`, 'success', 1800);
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  async function useVoiceInBuilder(voiceId) {
    selectedVoice = voiceId;
    builder = builder || {};
    builder.ttsVoice = voiceId;
    await saveBuilder(true);
    section = 'builder';
    $('lk-rail').querySelectorAll('.lk-rail-item').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.section === 'builder');
    });
    renderSection();
    UI.toast('Voice bound to the Agent Builder', 'success', 2000);
  }

  async function saveVoiceToAgent() {
    if (!selectedVoice) { UI.toast('Pick a voice first.', 'error'); return; }
    const agentId = voiceTargetAgent;
    if (!agentId) { UI.toast('Choose the agent that should use this voice.', 'error'); return; }
    try {
      const updated = await API.updateAgent(agentId, {
        voice: selectedVoice,
        ttsConfig: { model: selectedVoice },
        changeNote: `Voice set to ${selectedVoice}`,
      });
      UI.toast(`Voice saved to ${updated.name}`, 'success');
      await loadVoices();
      await loadAgents();
      renderSection();
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  function wireSection(root) {
    // Voices panel
    const search = root.querySelector('#lk-voice-search');
    if (search) {
      search.addEventListener('input', UI.debounce((event) => {
        voiceQuery = event.target.value.trim().toLowerCase();
        renderSection();
        const field = document.getElementById('lk-voice-search');
        if (field) { field.focus(); field.setSelectionRange(field.value.length, field.value.length); }
      }, 220));
    }
    root.querySelectorAll('[data-family]').forEach((btn) => {
      btn.addEventListener('click', () => {
        voiceFamily = btn.dataset.family;
        renderSection();
      });
    });
    root.querySelectorAll('[data-select-voice]').forEach((row) => {
      row.addEventListener('click', (event) => {
        if (event.target.closest('button')) return;
        selectedVoice = selectedVoice === row.dataset.selectVoice ? null : row.dataset.selectVoice;
        renderSection();
      });
    });
    root.querySelectorAll('[data-preview]').forEach((btn) => {
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        selectedVoice = btn.dataset.preview;
        previewVoice(btn.dataset.preview);
      });
    });
    root.querySelectorAll('[data-use-voice]').forEach((btn) => {
      btn.addEventListener('click', (event) => {
        event.stopPropagation();
        useVoiceInBuilder(btn.dataset.useVoice);
      });
    });
    const target = root.querySelector('#lk-voice-target');
    if (target) {
      target.addEventListener('change', (event) => { voiceTargetAgent = event.target.value; });
    }
    const simField = root.querySelector('#lk-sim-scenarios');
    if (simField) {
      simField.addEventListener('input', () => { simScenarios = simField.value; });
    }
    const saveBtn = root.querySelector('#lk-voice-save');
    if (saveBtn) saveBtn.addEventListener('click', saveVoiceToAgent);

    // Agent Builder
    ['lb-name', 'lb-agent', 'lb-stt', 'lb-llm', 'lb-tts', 'lb-voice', 'lb-turn'].forEach((id) => {
      const field = root.querySelector('#' + id);
      if (field) field.addEventListener('change', () => saveBuilder(true));
    });
    ['lb-greeting', 'lb-prompt'].forEach((id) => {
      const field = root.querySelector('#' + id);
      if (field) field.addEventListener('input', UI.debounce(() => saveBuilder(true), 500));
    });
    ['lb-interrupt', 'lb-preemptive'].forEach((id) => {
      const field = root.querySelector('#' + id);
      if (field) field.addEventListener('change', () => saveBuilder(true));
    });
    const generate = root.querySelector('#lb-generate');
    if (generate) {
      generate.addEventListener('click', async () => {
        const status = document.getElementById('lb-status');
        status.textContent = 'generating…';
        await saveBuilder(true);
        try {
          const res = await fetch('/api/livekit/build', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(builderFromForm() || builder),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'generate failed');
          builderFiles = data.files;
          status.textContent = `worker generated (${Object.keys(builderFiles).length} files)`;
          renderBuilderFiles();
        } catch (err) {
          status.textContent = 'failed';
          UI.toast(err.message, 'error');
        }
      });
    }
    const zip = root.querySelector('#lb-zip');
    if (zip) {
      zip.addEventListener('click', async () => {
        await saveBuilder(true);
        window.location.href = '/api/livekit/build.zip';
      });
    }
    const deploy = root.querySelector('#lb-deploy');
    if (deploy) {
      deploy.addEventListener('click', async () => {
        const out = document.getElementById('lb-output');
        const status = document.getElementById('lb-status');
        deploy.disabled = true;
        status.textContent = 'deploying…';
        out.classList.remove('hidden');
        out.textContent = 'Building the image and pushing it to LiveKit Cloud…';
        try {
          const res = await fetch('/api/livekit/deploy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(builderFromForm() || builder),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'deploy failed');
          status.textContent = data.ok ? 'deployed' : 'deploy failed';
          out.textContent = `${data.command}\n\n${data.output || '(no output)'}`;
        } catch (err) {
          status.textContent = 'deploy failed';
          out.classList.remove('hidden');
          out.textContent = `${err.message}\n\nRun it from a machine with Docker, or download the ZIP and deploy manually.`;
        } finally {
          deploy.disabled = false;
        }
      });
    }
  }

  function renderBuilderFiles() {
    const tabs = document.getElementById('lb-file-tabs');
    const code = document.getElementById('lb-code');
    if (!tabs || !code || !builderFiles) return;
    const names = Object.keys(builderFiles);
    tabs.innerHTML = names.map((name, index) => `
      <button class="btn btn-xs ${index === 0 ? 'btn-primary' : 'btn-outline'}" data-file="${UI.esc(name)}" type="button">${UI.esc(name)}</button>`).join('');
    tabs.querySelectorAll('[data-file]').forEach((btn) => {
      btn.addEventListener('click', () => {
        code.textContent = builderFiles[btn.dataset.file] || '';
        tabs.querySelectorAll('[data-file]').forEach((b) => b.classList.toggle('btn-primary', b === btn));
      });
    });
    code.textContent = builderFiles[names[0]] || '';
  }

  await loadVoices();
  await loadAgents();
  await loadBuilder();

  if (location.hash === '#builder') {
    section = 'builder';
    $('lk-rail').querySelectorAll('.lk-rail-item').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.section === 'builder');
    });
  }

  await loadConsole();
})();

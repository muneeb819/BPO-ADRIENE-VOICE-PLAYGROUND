/* LiveKit Cloud - connect, control, use, build and deploy LiveKit voice agents. */
'use strict';

(async function initLivekit() {
  await Shell.mount('livekit');

  const $ = (id) => document.getElementById(id);
  let status = null;
  let rooms = [];
  let bundle = null;
  let activeFile = 'agent.py';

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '12 — LiveKit Cloud',
    title: 'LiveKit Cloud',
    sub: 'Everything this project does with LiveKit: project status, live rooms, agent dispatch, join tokens and a worker builder that emits a deployable agent.',
    right: `<a class="btn btn-outline" href="/deepgram">${Shell.icon('bolt')} Deepgram</a>
      <a class="btn btn-primary" href="/admin">${Shell.icon('grid')} Admin Panel</a>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  // --- voice catalogue (Deepgram voices usable as the TTS voice) -----------
  function populateVoices() {
    const select = $('lk-b-voice');
    if (!window.VOICE_CATALOG) return;
    const groups = [
      ['Deepgram Flux', window.VOICE_CATALOG.flux],
      ['Deepgram Aura', window.VOICE_CATALOG.aura],
    ];
    select.innerHTML = groups.map(([label, voices]) => `
      <optgroup label="${label}">
        ${voices.map((v) => `<option value="${v.id}">${v.family} - ${v.name} (${v.accent}, ${v.gender})</option>`).join('')}
      </optgroup>`).join('');
    select.value = 'flux-brittany-en';
  }

  // --- rendering ----------------------------------------------------------
  function renderStatus() {
    const pill = $('lk-state');
    const body = $('lk-connection-body');
    if (!status) return;
    if (!status.configured) {
      pill.textContent = 'not configured';
      pill.className = 'pill pill-red-dark';
      body.innerHTML = `<div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-[10px] leading-relaxed text-amber-200 sm:col-span-2 lg:col-span-4">${UI.esc(status.message || 'Add LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET to .env and restart the server.')}</div>`;
      return;
    }
    pill.textContent = status.connected ? 'connected' : 'unreachable';
    pill.className = `pill ${status.connected ? 'pill-green-dark' : 'pill-red-dark'}`;
    body.innerHTML = `
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Project</div>
        <div class="mt-1 truncate text-[10.5px] font-bold text-slate-100">${UI.esc(status.host || '')}</div>
        <div class="mono mt-0.5 truncate text-[8px] text-slate-500">${UI.esc(status.url || '')}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Agent dispatch</div>
        <div class="mt-1 truncate text-[10.5px] font-bold text-slate-100">${UI.esc(status.agentName || 'not set')}</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">${status.connected ? `latency ${status.latencyMs ?? '—'} ms` : 'not reachable'}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Live rooms</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">${status.rooms ?? 0} room(s)</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">${status.participants ?? 0} participant(s)</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">API key</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">Server only</div>
        <div class="mt-0.5 text-[8.5px] text-slate-500">never sent to the browser</div>
      </div>`;
  }

  function renderCloud() {
    const cloud = status?.cloudApi || {};
    const pill = $('lk-cloud-state');
    const body = $('lk-cloud-body');
    if (cloud.authorized) {
      pill.textContent = 'authorized';
      pill.className = 'pill pill-green no-dot';
      const agents = cloud.agents || [];
      body.innerHTML = agents.length
        ? `<div class="space-y-1.5">${agents.map((a) => `<div class="rounded-lg border border-slate-200/60 bg-slate-50/40 px-2.5 py-1.5">
            <div class="text-[9.5px] font-semibold text-slate-700">${UI.esc(a.name || a.id || 'agent')}</div>
            <div class="mono mt-0.5 text-[8px] text-slate-400">${UI.esc(a.id || '')}</div>
          </div>`).join('')}</div>`
        : '<div class="text-[9.5px] text-slate-500">No agents returned by the Cloud API.</div>';
      return;
    }
    pill.textContent = cloud.configured ? 'forbidden' : 'no cloud key';
    pill.className = 'pill pill-amber no-dot';
    body.innerHTML = `<div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-[9.5px] leading-relaxed text-amber-200">
        ${UI.esc(cloud.message || 'Cloud API key not configured.')}
        <div class="mt-1.5 text-slate-300">The project key controls rooms and dispatch. Managing <span class="mono">agents, versions, builds</span> and <span class="mono">secrets</span> needs a Cloud API key:</div>
        <div class="mono mt-1 rounded bg-black/30 px-2 py-1 text-[8.5px] text-slate-200">lk cloud api-key create</div>
        <div class="mt-1">Then set <span class="mono">LIVEKIT_CLOUD_API_KEY</span> and <span class="mono">LIVEKIT_CLOUD_API_SECRET</span> in <span class="mono">.env</span>.</div>
      </div>`;
  }

  function renderRooms() {
    $('lk-rooms-count').textContent = `${rooms.length} live`;
    $('lk-rooms').innerHTML = rooms.length
      ? rooms.map((room) => `<div class="rounded-xl border border-slate-200/70 bg-slate-50/40 p-2.5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="truncate text-[10.5px] font-extrabold text-slate-800">${UI.esc(room.name)}</span>
            <span class="chip chip-mono">${room.participants} participant(s)</span>
          </div>
          ${(room.participantList || []).length ? `<div class="mt-1.5 space-y-1">${room.participantList.map((p) => `<div class="flex items-center justify-between gap-2 text-[9px] text-slate-500">
            <span class="truncate">${UI.esc(p.name || p.identity)}${p.isAgent ? ' · agent' : ''}</span>
            <span class="chip">${UI.esc(p.state)}</span>
          </div>`).join('')}</div>` : '<div class="mt-1 text-[9px] text-slate-400">No participants</div>'}
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button class="btn btn-xs btn-outline" data-dispatch="${UI.esc(room.name)}" type="button"><span data-icon="bot"></span> Dispatch agent</button>
            <button class="btn btn-xs btn-soft" data-token="${UI.esc(room.name)}" type="button"><span data-icon="key"></span> Token</button>
            <button class="btn btn-xs btn-danger" data-delete="${UI.esc(room.name)}" type="button"><span data-icon="trash"></span> Delete</button>
          </div>
        </div>`).join('')
      : '<div class="empty-state"><div class="empty-title">No live rooms</div><div class="empty-sub">Create a room to dispatch the agent into it.</div></div>';

    $('lk-rooms').querySelectorAll('[data-dispatch]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const res = await fetch('/api/livekit/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room: btn.dataset.dispatch }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'dispatch failed');
          UI.toast(`Agent dispatched to ${data.room} (${data.agentName})`, 'success');
          await loadRooms();
        } catch (err) {
          UI.toast(err.message, 'error');
        } finally {
          btn.disabled = false;
        }
      });
    });
    $('lk-rooms').querySelectorAll('[data-token]').forEach((btn) => {
      btn.addEventListener('click', () => {
        $('lk-token-room').value = btn.dataset.token;
        mintToken();
      });
    });
    $('lk-rooms').querySelectorAll('[data-delete]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const res = await fetch(`/api/livekit/rooms/${encodeURIComponent(btn.dataset.delete)}`, { method: 'DELETE' });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'delete failed');
          UI.toast(`Room ${btn.dataset.delete} deleted`, 'success');
          await loadRooms();
        } catch (err) {
          UI.toast(err.message, 'error');
        } finally {
          btn.disabled = false;
        }
      });
    });
    $('lk-rooms').querySelectorAll('[data-icon]').forEach((el) => {
      el.innerHTML = Shell.icon(el.dataset.icon, 'w-3 h-3');
    });
  }

  // --- actions ------------------------------------------------------------
  async function loadStatus() {
    try {
      const res = await fetch('/api/livekit/status');
      status = await res.json();
      renderStatus();
      renderCloud();
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  async function loadRooms() {
    if (!status?.configured) return;
    try {
      const res = await fetch('/api/livekit/rooms');
      const data = await res.json();
      rooms = data.rooms || [];
      renderRooms();
    } catch (err) {
      $('lk-rooms').innerHTML = `<div class="text-[10px] text-red-300">${UI.esc(err.message)}</div>`;
    }
  }

  async function mintToken() {
    const room = $('lk-token-room').value.trim();
    const identity = $('lk-token-identity').value.trim() || 'adriene-operator';
    if (!room) {
      UI.toast('Room name is required.', 'error');
      return;
    }
    try {
      const res = await fetch('/api/livekit/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room, identity }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'token failed');
      const out = $('lk-token-output');
      out.classList.remove('hidden');
      out.textContent = `url=${data.url}\nroom=${data.room}\nidentity=${data.identity}\ntoken=${data.token}`;
      UI.toast('Join token minted', 'success');
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  $('lk-create-room').addEventListener('click', async () => {
    const name = $('lk-room-name').value.trim();
    if (!name) {
      UI.toast('Room name is required.', 'error');
      return;
    }
    try {
      const res = await fetch('/api/livekit/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'create failed');
      UI.toast(`Room ${name} created`, 'success');
      $('lk-room-name').value = '';
      await loadRooms();
      await loadStatus();
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  });

  $('lk-mint-token').addEventListener('click', mintToken);

  $('lk-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    await loadStatus();
    await loadRooms();
    btn.disabled = false;
  });

  // --- builder -------------------------------------------------------------
  $('lk-b-build').addEventListener('click', async () => {
    const btn = $('lk-b-build');
    btn.disabled = true;
    $('lk-b-status').textContent = 'Generating…';
    try {
      const res = await fetch('/api/livekit/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: $('lk-b-name').value.trim(),
          sttModel: $('lk-b-stt').value.trim(),
          llmModel: $('lk-b-llm').value.trim(),
          ttsModel: $('lk-b-tts').value.trim(),
          ttsVoice: $('lk-b-voice').value,
          greeting: $('lk-b-greeting').value.trim(),
          prompt: $('lk-b-prompt').value,
          preemptive: $('lk-b-preemptive').checked,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'build failed');
      bundle = data.files;
      activeFile = 'agent.py';
      $('lk-b-output-wrap').classList.remove('hidden');
      $('lk-b-download').disabled = false;
      $('lk-b-status').textContent = `Generated ${Object.keys(bundle).length} file(s)`;
      $('lk-b-deploy').textContent = `${data.deployCommand} — or push the files to LiveKit Cloud and run “python agent.py start”.`;
      renderBundle();
    } catch (err) {
      $('lk-b-status').textContent = 'Failed';
      UI.toast(err.message, 'error');
    } finally {
      btn.disabled = false;
    }
  });

  function renderBundle() {
    if (!bundle) return;
    $('lk-b-output').textContent = bundle[activeFile] || '';
    $('lk-b-tabs').innerHTML = Object.keys(bundle).map((name) => `
      <button class="btn btn-xs ${name === activeFile ? 'btn-primary' : 'btn-outline'}" data-file="${name}" type="button">${name}</button>`).join('');
    $('lk-b-tabs').querySelectorAll('[data-file]').forEach((btn) => {
      btn.addEventListener('click', () => {
        activeFile = btn.dataset.file;
        renderBundle();
      });
    });
  }

  $('lk-b-download').addEventListener('click', () => {
    if (!bundle) return;
    const content = bundle[activeFile] || '';
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = activeFile;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    UI.toast(`${activeFile} downloaded`, 'success');
  });

  populateVoices();
  await loadStatus();
  await loadRooms();
})();

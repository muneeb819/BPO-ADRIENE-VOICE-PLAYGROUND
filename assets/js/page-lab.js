/* Voice Lab & provider adapters */
'use strict';

(async function initLab() {
  await Shell.mount('lab');

  const $ = (id) => document.getElementById(id);
  let providers = [];
  let health = null;
  let filter = 'all';
  let previewUtterance = null;
  let cloudTtsUrl = null;
  let selectedFile = null;
  const lastTest = new Map();

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '05 — Voice Lab & Provider Adapters',
    title: 'Voice Lab',
    sub: 'Independent STT • LLM • TTS adapters. Swappable without rewriting the conversation engine. Keys stay backend-only.',
    right: `<div class="flex items-center gap-1.5" role="group" aria-label="Filter providers">
      <button class="filter-btn active" data-filter="all" type="button">ALL</button>
      <button class="filter-btn" data-filter="stt" type="button">STT</button>
      <button class="filter-btn" data-filter="llm" type="button">LLM</button>
      <button class="filter-btn" data-filter="tts" type="button">TTS</button>
    </div>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });

  // ---- provider rendering ------------------------------------------------

  function audioFormat(p) {
    if (p.type === 'stt') return '16kHz · PCM · streaming';
    if (p.type === 'llm') return 'Text · streaming tokens';
    return '24kHz · MP3 · streaming';
  }

  function timeoutLabel(p) {
    if (p.type === 'tts') return 'Connect 5s • First audio 2s';
    if (p.type === 'stt') return 'Connect 5s • Final 2s';
    return 'Connect 5s • First token 2s';
  }

  function adapterCard(p) {
    const status = lastTest.get(p.id)?.status || p.status || 'disconnected';
    return `<button class="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-left transition hover:border-violet-300 hover:bg-violet-50/20" data-focus-provider="${p.id}" type="button">
      <div class="flex items-center justify-between gap-2">
        <span class="truncate text-[11px] font-extrabold tracking-tight text-slate-800">${UI.esc(p.displayName)}</span>
        ${UI.statusPill(status)}
      </div>
      <div class="mt-1 truncate text-[8.5px] text-slate-400">${UI.esc(p.name)} · ${UI.esc((p.capabilities || []).join(' · '))}</div>
    </button>`;
  }

  function renderGroups() {
    ['stt', 'llm', 'tts'].forEach((type) => {
      const list = providers.filter((p) => p.type === type);
      $(`${type}-count`).textContent = `${list.length} adapter${list.length === 1 ? '' : 's'}`;
      $(`${type}-list`).innerHTML = list.length
        ? list.map(adapterCard).join('')
        : UI.emptyState('No adapters', 'Seed the provider registry from server.py.', 'server');
      $(`group-${type}`).classList.toggle('hidden', filter !== 'all' && filter !== type);
    });
  }

  function providerCard(p) {
    const result = lastTest.get(p.id);
    const status = result?.status || p.status || 'disconnected';
    const config = JSON.stringify(p.config || {});
    return `<div class="rounded-xl border border-slate-300 bg-white p-3" id="provider-card-${p.id}">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-1.5">
            <h3 class="text-[12px] font-extrabold tracking-tight text-slate-900">${UI.esc(p.displayName)}</h3>
            <span class="text-[9px] text-slate-400">(${UI.esc(p.name)})</span>
            ${UI.statusPill(status)}
          </div>
          <div class="mt-1 text-[9px] text-slate-500">Type: ${UI.providerTypeLabel(p.type)} • Default: ${p.isDefault ? 'Yes' : 'No'} • Enabled: ${p.isEnabled ? 'Yes' : 'No'}</div>
        </div>
        <button class="btn btn-dark btn-xs" data-test-provider="${p.id}" type="button">Test Connection</button>
      </div>
      <pre class="mt-2 overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 font-mono text-[9px] leading-relaxed text-slate-600">config: ${UI.esc(config)}</pre>
      <div class="mt-2 grid grid-cols-2 gap-2">
        <div class="rounded-lg border border-slate-200 px-2 py-1.5">
          <div class="text-[7.5px] font-extrabold uppercase tracking-[0.1em] text-slate-400">Audio format</div>
          <div class="mt-0.5 text-[9px] font-medium text-slate-600">${UI.esc(audioFormat(p))}</div>
        </div>
        <div class="rounded-lg border border-slate-200 px-2 py-1.5">
          <div class="text-[7.5px] font-extrabold uppercase tracking-[0.1em] text-slate-400">Timeout</div>
          <div class="mt-0.5 text-[9px] font-medium text-slate-600">${UI.esc(timeoutLabel(p))}</div>
        </div>
      </div>
      ${result ? `<div class="mt-2 rounded-lg border px-2.5 py-1.5 text-[9.5px] leading-relaxed ${result.status === 'connected' ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-red-200 bg-red-50 text-red-700'}">
        <b>${result.status === 'connected' ? 'Pass' : 'Fail'}</b> · ${UI.esc(result.message || '')} ${result.latencyMs !== undefined ? `· ${result.latencyMs} ms` : ''}
      </div>` : ''}
    </div>`;
  }

  function visibleProviders() {
    return filter === 'all' ? providers : providers.filter((p) => p.type === filter);
  }

  function renderCatalogue() {
    const list = visibleProviders();
    $('catalogue-count').textContent = `${list.length} adapter${list.length === 1 ? '' : 's'}`;
    $('catalogue').innerHTML = list.length
      ? list.map(providerCard).join('')
      : UI.emptyState('No adapters match this filter', 'Choose another provider family.', 'server');
  }

  function renderStatusTiles() {
    const connectedStt = providers.filter((p) => p.type === 'stt' && p.status === 'connected');
    const connectedTts = providers.filter((p) => p.type === 'tts' && p.status === 'connected');
    $('stt-pass').textContent = connectedStt.length
      ? `${connectedStt.map((p) => p.name === 'browser' ? 'Browser' : p.displayName.split(' ')[0]).slice(0, 2).join(' + ')} ✓`
      : 'No path';
    $('tts-pass').textContent = connectedTts.length
      ? `${connectedTts.map((p) => p.name === 'browser-tts' ? 'Browser' : p.displayName.split(' ')[0]).slice(0, 2).join(' + ')} ✓`
      : 'No path';
    $('local-tts').textContent = 'speechSynthesis' in window ? 'Browser ready' : 'Unavailable';
  }

  function renderAll() {
    renderGroups();
    renderCatalogue();
    renderStatusTiles();
  }

  function setFilter(next) {
    filter = next;
    document.querySelectorAll('.filter-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.filter === next);
    });
    renderAll();
  }

  function focusProvider(id) {
    const p = providers.find((x) => x.id === id);
    if (!p) return;
    if (filter !== 'all' && filter !== p.type) {
      setFilter(p.type);
    }
    requestAnimationFrame(() => {
      const el = document.getElementById(`provider-card-${p.id}`);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-violet-300');
      setTimeout(() => el.classList.remove('ring-2', 'ring-violet-300'), 1400);
    });
  }

  // ---- provider tests ----------------------------------------------------

  async function testProvider(id, button) {
    button.disabled = true;
    button.textContent = 'Testing…';
    try {
      const result = await API.testProvider(id);
      const p = providers.find((x) => x.id === id);
      if (p) {
        p.status = result.status;
        p.lastTestedAt = result.testedAt || new Date().toISOString();
      }
      lastTest.set(id, result);
      renderAll();
      UI.toast(`${result.status === 'connected' ? 'Connected' : 'Test failed'}: ${result.message}`, result.status === 'connected' ? 'success' : 'error');
      if (result.status !== 'connected') {
        $('err-provider-note')?.classList.remove('hidden');
      }
    } catch (err) {
      lastTest.set(id, { status: 'error', message: err.message, latencyMs: undefined });
      renderAll();
      UI.toast(err.message, 'error');
    }
  }

  $('catalogue').addEventListener('click', (event) => {
    const test = event.target.closest('[data-test-provider]');
    if (test) {
      testProvider(test.dataset.testProvider, test);
      return;
    }
    const focus = event.target.closest('[data-focus-provider]');
    if (focus) focusProvider(focus.dataset.focusProvider);
  });

  document.querySelectorAll('.filter-btn').forEach((btn) => {
    btn.addEventListener('click', () => setFilter(btn.dataset.filter));
  });

  // The adapter cards live outside the catalogue; delegate their clicks.
  ['stt', 'llm', 'tts'].forEach((type) => {
    $(`${type}-list`).addEventListener('click', (event) => {
      const focus = event.target.closest('[data-focus-provider]');
      if (focus) focusProvider(focus.dataset.focusProvider);
    });
  });

  // ---- browser voice preview --------------------------------------------

  function resetPreview() {
    previewUtterance = null;
    $('preview-btn').disabled = false;
    $('preview-btn').innerHTML = `${Shell.icon('play')} Preview with Browser TTS`;
    $('preview-stop').disabled = true;
  }

  function previewVoice() {
    const text = $('preview-text').value.trim();
    if (!text) {
      UI.toast('Enter sample text to preview.', 'error');
      return;
    }
    if (!('speechSynthesis' in window)) {
      UI.toast('Browser speech synthesis is unavailable.', 'error');
      return;
    }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'en-US';
    u.rate = Number($('preview-rate').value) / 100;
    u.pitch = 1;
    previewUtterance = u;
    u.onstart = () => {
      $('preview-btn').disabled = true;
      $('preview-btn').textContent = 'Speaking…';
      $('preview-stop').disabled = false;
    };
    u.onend = resetPreview;
    u.onerror = resetPreview;
    window.speechSynthesis.speak(u);
  }

  $('preview-btn').addEventListener('click', previewVoice);
  $('preview-stop').addEventListener('click', () => {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    resetPreview();
  });
  $('preview-rate').addEventListener('input', () => {
    $('preview-rate-value').textContent = `${$('preview-rate').value}%`;
  });
  $('preview-stability').addEventListener('input', () => {
    $('preview-stability-value').textContent = Number($('preview-stability').value).toFixed(1);
  });
  $('preview-stop').disabled = true;

  // ---- Deepgram voice picker ---------------------------------------------

  const voicePicker = $('cloud-tts-voice-picker');
  const voiceTrigger = $('cloud-tts-voice-trigger');
  const voiceMenu = $('cloud-tts-voice-menu');
  const voiceInput = $('cloud-tts-voice');
  let selectedVoiceId = voiceInput.value;

  function renderVoiceMenu() {
    const catalog = window.VOICE_CATALOG;
    if (!catalog) return;
    const groups = [
      { label: 'Flux', voices: catalog.flux },
      { label: 'Aura', voices: catalog.aura },
    ];
    voiceMenu.innerHTML = groups.map((group) => `
      <div class="voice-menu-group">${group.label}</div>
      ${group.voices.map((voice) => `
        <button class="voice-option${voice.id === selectedVoiceId ? ' selected' : ''}" type="button"
          data-voice-id="${voice.id}" role="option" aria-selected="${voice.id === selectedVoiceId}">
          <span class="voice-option-name">${UI.esc(voice.name)}</span>
          <span class="voice-option-meta">(${UI.esc(voice.accent)}, ${UI.esc(voice.gender)})</span>
          <span class="voice-check" aria-hidden="true">${Shell.icon('check')}</span>
        </button>`).join('')}
    `).join('');
  }

  function setSelectedVoice(id, focusTrigger = false) {
    const catalog = window.VOICE_CATALOG;
    if (!catalog) return;
    const voice = catalog.byId(id) || catalog.byId('flux-brittany-en');
    if (!voice) return;
    selectedVoiceId = voice.id;
    voiceInput.value = voice.id;
    $('cloud-tts-voice-name').textContent = `${voice.family} — ${voice.name}`;
    $('cloud-tts-voice-meta').textContent = `(${voice.accent}, ${voice.gender})`;
    voiceMenu.querySelectorAll('.voice-option').forEach((option) => {
      const selected = option.dataset.voiceId === voice.id;
      option.classList.toggle('selected', selected);
      option.setAttribute('aria-selected', String(selected));
    });
    if (focusTrigger) voiceTrigger.focus();
  }

  function openVoiceMenu() {
    voiceMenu.classList.remove('hidden');
    voiceTrigger.setAttribute('aria-expanded', 'true');
    const selected = voiceMenu.querySelector('.voice-option.selected');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
  }

  function closeVoiceMenu() {
    voiceMenu.classList.add('hidden');
    voiceTrigger.setAttribute('aria-expanded', 'false');
  }

  voiceTrigger.addEventListener('click', () => {
    if (voiceMenu.classList.contains('hidden')) openVoiceMenu();
    else closeVoiceMenu();
  });

  voiceMenu.addEventListener('click', (event) => {
    const option = event.target.closest('[data-voice-id]');
    if (!option) return;
    setSelectedVoice(option.dataset.voiceId, true);
    closeVoiceMenu();
  });

  document.addEventListener('click', (event) => {
    if (!voicePicker.contains(event.target)) closeVoiceMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !voiceMenu.classList.contains('hidden')) {
      closeVoiceMenu();
      voiceTrigger.focus();
    }
  });

  voiceTrigger.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      openVoiceMenu();
      (voiceMenu.querySelector('.voice-option.selected') || voiceMenu.querySelector('.voice-option'))?.focus();
    }
  });

  voiceMenu.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const options = [...voiceMenu.querySelectorAll('.voice-option')];
    const current = options.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'ArrowDown'
      ? options[Math.min(options.length - 1, current + 1)]
      : options[Math.max(0, current - 1)];
    next.focus();
  });

  renderVoiceMenu();
  setSelectedVoice(selectedVoiceId);

  // ---- cloud TTS smoke ---------------------------------------------------

  let lastPlayKey = '';

  function voiceLabel(voiceId) {
    const voice = window.VOICE_CATALOG?.byId(voiceId);
    if (voice) return `${voice.family} — ${voice.name} (${voice.accent}, ${voice.gender})`;
    return voiceId || 'unknown voice';
  }

  $('cloud-tts-btn').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    const text = $('cloud-tts-text').value.trim();
    if (!text) {
      UI.toast('Enter text to play.', 'error');
      return;
    }
    const voice = $('cloud-tts-voice').value;
    const key = `${voice}|${text}`;
    const audio = $('cloud-tts-audio');
    if (lastPlayKey === key && cloudTtsUrl) {
      audio.src = cloudTtsUrl;
      audio.classList.remove('hidden');
      await audio.play().catch(() => {});
      $('cloud-tts-status').textContent = 'Playing…';
      return;
    }
    UI.setBusy(btn, true, 'Playing…');
    $('cloud-tts-error').classList.add('hidden');
    const selectedVoice = window.VOICE_CATALOG?.byId(voice);
    $('cloud-tts-status').textContent = `Calling Deepgram ${selectedVoice?.family || 'TTS'}…`;
    const started = performance.now();
    try {
      const blob = await API.tts(text, voice);
      const ms = Math.round(performance.now() - started);
      if (cloudTtsUrl) URL.revokeObjectURL(cloudTtsUrl);
      cloudTtsUrl = URL.createObjectURL(blob);
      lastPlayKey = key;
      audio.src = cloudTtsUrl;
      audio.classList.remove('hidden');
      audio.play().catch(() => {});
      const dl = $('cloud-tts-download');
      dl.href = cloudTtsUrl;
      dl.classList.remove('hidden');
      $('cloud-tts-status').textContent = `${ms} ms · ${(blob.size / 1024).toFixed(1)} KB`;
      UI.toast(`Deepgram audio ready (${ms} ms)`, 'success');
    } catch (err) {
      $('cloud-tts-status').textContent = 'Failed';
      const box = $('cloud-tts-error');
      box.textContent = `${err.message}. Add DEEPGRAM_API_KEY to .env and restart server.py; browser TTS remains available in the playground.`;
      box.classList.remove('hidden');
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  // ---- save the selected voice to an agent --------------------------------

  let agentOptions = [];

  async function loadAgentOptions() {
    const select = $('cloud-tts-agent');
    try {
      agentOptions = await API.agents();
      select.innerHTML = agentOptions.map((agent) => `
        <option value="${agent.id}">${UI.esc(agent.name)} — ${UI.esc(voiceLabel(agent.voice))}</option>`).join('');
      if (!select.value && select.options.length) select.selectedIndex = 0;
    } catch (err) {
      select.innerHTML = '<option value="">No agents available</option>';
    }
  }

  $('cloud-tts-save').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    const agentId = $('cloud-tts-agent').value;
    const voice = $('cloud-tts-voice').value;
    if (!agentId) {
      UI.toast('No agent selected.', 'error');
      return;
    }
    UI.setBusy(btn, true, 'Saving');
    try {
      const updated = await API.updateAgent(agentId, {
        voice,
        ttsConfig: { model: voice },
        changeNote: `Voice set to ${voiceLabel(voice)}`,
      });
      UI.toast(`Voice saved to ${updated.name}`, 'success');
      $('cloud-tts-status').textContent = `Saved to ${updated.name}`;
      await loadAgentOptions();
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  // ---- cloud STT smoke ---------------------------------------------------

  function setSelectedFile(file) {
    selectedFile = file;
    if (!file) {
      $('stt-file-label').textContent = 'Drop an audio file or click to browse';
      $('cloud-stt-btn').disabled = true;
      $('cloud-stt-status').textContent = 'Choose a file';
      return;
    }
    $('stt-file-label').textContent = `${file.name} · ${(file.size / 1024).toFixed(0)} KB`;
    $('cloud-stt-btn').disabled = !health?.capabilities?.deepgramStt;
    $('cloud-stt-status').textContent = health?.capabilities?.deepgramStt ? 'Ready to transcribe' : 'Deepgram key required';
    $('stt-result').classList.add('hidden');
    $('stt-error').classList.add('hidden');
  }

  $('stt-file').addEventListener('change', (event) => {
    setSelectedFile(event.target.files?.[0] || null);
  });

  const drop = $('stt-drop');
  ['dragenter', 'dragover'].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.add('border-violet-400', 'bg-violet-50/40');
    });
  });
  ['dragleave', 'drop'].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.remove('border-violet-400', 'bg-violet-50/40');
    });
  });
  drop.addEventListener('drop', (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) setSelectedFile(file);
  });

  $('cloud-stt-btn').addEventListener('click', async (event) => {
    if (!selectedFile) return;
    const btn = event.currentTarget;
    UI.setBusy(btn, true, 'Transcribing');
    $('stt-error').classList.add('hidden');
    $('stt-result').classList.add('hidden');
    $('cloud-stt-status').textContent = 'Uploading to local API…';
    const started = performance.now();
    try {
      const data = await API.stt(selectedFile);
      const ms = Math.round(performance.now() - started);
      $('stt-transcript').textContent = data.transcript || '(empty transcript)';
      $('stt-meta').textContent = `${data.provider || 'provider'} · ${data.model || ''} · ${ms} ms`;
      $('stt-result').classList.remove('hidden');
      $('cloud-stt-status').textContent = `${ms} ms`;
      UI.toast('Transcription complete', 'success');
    } catch (err) {
      const box = $('stt-error');
      box.textContent = `${err.message}. Browser STT remains available in the Voice Playground.`;
      box.classList.remove('hidden');
      $('cloud-stt-status').textContent = 'Failed';
      UI.toast(err.message, 'error');
    } finally {
      UI.setBusy(btn, false);
    }
  });

  // ---- Deepgram account ---------------------------------------------------

  function renderDeepgramAccount(info) {
    const body = $('dg-account-body');
    const pill = $('dg-account-pill');
    if (!info || !info.connected) {
      pill.textContent = 'not connected';
      pill.className = 'pill pill-red-dark';
      body.innerHTML = `<div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-[10px] text-amber-200 sm:col-span-2 lg:col-span-4">${UI.esc(info?.message || 'Add DEEPGRAM_API_KEY to .env and restart the server to connect your Deepgram project.')}</div>`;
      return;
    }
    pill.textContent = 'connected';
    pill.className = 'pill pill-green-dark';
    const project = info.project || {};
    const models = (info.sttModels || []).slice(0, 6);
    const llm = (info.llmModels || []).map((m) => m.label);
    body.innerHTML = `
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Project</div>
        <div class="mt-1 truncate text-[10.5px] font-bold text-slate-100">${UI.esc(project.name || 'Deepgram project')}</div>
        <div class="mono mt-0.5 truncate text-[8px] text-slate-500">${UI.esc(project.id || '')}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Speech to text</div>
        <div class="mt-1 flex flex-wrap gap-1">${models.map((m) => `<span class="chip chip-mono">${UI.esc(m)}</span>`).join('') || '<span class="text-[10px] text-slate-500">—</span>'}</div>
        <div class="mt-1 text-[8.5px] text-slate-500">${info.availableModels ? `${info.availableModels} models visible on this key` : 'Deepgram Nova'}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Text to speech</div>
        <div class="mt-1 text-[10.5px] font-bold text-slate-100">${info.tts?.voices || 0} voices</div>
        <div class="mt-0.5 flex flex-wrap gap-1">${(info.tts?.families || []).map((f) => `<span class="chip">${UI.esc(f)}</span>`).join('')}</div>
      </div>
      <div class="rounded-lg border border-slate-700/60 bg-slate-900/60 p-2.5">
        <div class="text-[8px] font-extrabold uppercase tracking-[0.12em] text-slate-500">Voice agent models</div>
        <div class="mt-1 space-y-0.5">${llm.map((label) => `<div class="truncate text-[9.5px] text-slate-300">${UI.esc(label)}</div>`).join('') || '<span class="text-[10px] text-slate-500">—</span>'}</div>
      </div>`;
  }

  async function loadDeepgramAccount() {
    const pill = $('dg-account-pill');
    pill.textContent = 'checking';
    pill.className = 'pill pill-dark';
    try {
      const res = await fetch('/api/deepgram/account');
      const info = await res.json();
      renderDeepgramAccount(info);
    } catch (err) {
      renderDeepgramAccount({ connected: false, message: err.message });
    }
  }

  $('dg-account-refresh').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    await loadDeepgramAccount();
    btn.disabled = false;
  });

  // ---- boot --------------------------------------------------------------

  try {
    const [providerList, healthData] = await Promise.all([API.providers(), API.health()]);
    providers = providerList;
    health = healthData;
  } catch (err) {
    UI.toast(err.message, 'error');
  }

  renderAll();
  await loadAgentOptions();
  await loadDeepgramAccount();

  if (health) {
    const ttsReady = !!health.capabilities?.deepgramTts;
    const sttReady = !!health.capabilities?.deepgramStt;
    $('cloud-tts-pill').textContent = ttsReady ? 'configured' : 'missing key';
    $('cloud-tts-pill').className = `pill ${ttsReady ? 'pill-green-dark' : 'pill-red-dark'}`;
    $('cloud-stt-pill').textContent = sttReady ? 'configured' : 'missing key';
    $('cloud-stt-pill').className = `pill ${sttReady ? 'pill-green' : 'pill-red'}`;
    $('cloud-tts-btn').disabled = !ttsReady;
    if (!ttsReady) {
      $('cloud-tts-status').textContent = 'DEEPGRAM_API_KEY not configured';
      const box = $('cloud-tts-error');
      box.textContent = 'Add DEEPGRAM_API_KEY to .env and restart server.py to synthesize with Deepgram Flux or Aura. The preview above uses your browser voice and works offline.';
      box.classList.remove('hidden');
    }
    if (!sttReady) {
      const box = $('stt-error');
      box.textContent = 'Add DEEPGRAM_API_KEY to .env and restart server.py to transcribe uploads with Deepgram Nova-2. Browser STT remains available in the playground.';
      box.classList.remove('hidden');
    }
    $('cloud-stt-btn').disabled = true;
  }
})();

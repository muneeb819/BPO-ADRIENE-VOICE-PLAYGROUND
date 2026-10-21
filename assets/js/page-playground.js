/* Voice Playground */
'use strict';

(async function initPlayground() {
  await Shell.mount('playground');

  const $ = (id) => document.getElementById(id);
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  let agents = [];
  let providers = [];
  let agent = null;
  let health = null;
  let session = null;
  let busy = false;
  let micOn = false;
  let micStream = null;
  let audioCtx = null;
  let analyser = null;
  let levelRaf = null;
  let recognition = null;
  let recognitionActive = false;
  let sttAuto = true;
  let soundOn = localStorage.getItem('adriene:sound') !== 'off';
  let lastFinal = '';
  let lastFinalAt = 0;
  let voiceHeardAt = 0;
  let silenceTimer = null;
  let silencePrompted = false;
  let mediaRecorder = null;
  let recordChunks = [];
  let recording = false;
  let resumeRecognitionAfterClip = false;
  let playing = false;
  let stopRequested = false;
  let playResolve = null;
  let currentAudio = null;
  let currentAudioUrl = null;
  let fallbackNoted = false;
  let metrics = { stt: null, llmFirst: null, llm: null, tts: null, e2e: null, turns: 0 };

  document.getElementById('page-header').innerHTML = Shell.header({
    eyebrow: '03 — Voice Playground',
    title: 'Voice Playground',
    sub: 'A real mic → STT → deterministic policy → TTS loop, with explicit consent, barge-in control and browser-measured latency.',
    right: `<span class="pill pill-green" id="pg-api-pill">Local API</span>
      <span class="pill pill-red" id="pg-tel-pill">Telephony Off</span>
      <span class="pill pill-ghost no-dot">Audio stays local</span>`,
  });

  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = Shell.icon(el.dataset.icon, 'w-3.5 h-3.5');
  });
  $('refresh-session').innerHTML = Shell.icon('refresh', 'w-3.5 h-3.5');
  $('start-btn').innerHTML = `${Shell.icon('play')} Start Session`;
  $('send-btn').innerHTML = `${Shell.icon('send')} Send`;

  // ---- helpers -----------------------------------------------------------

  // The browser only exposes microphone capture in a secure context
  // (https, or http on localhost). The mic therefore works on the published
  // HTTPS address; on plain HTTP we point the user at it instead of failing
  // silently.
  function secureContext() {
    return window.isSecureContext !== false;
  }

  function micHttpsUrl() {
    const host = location.hostname || 'localhost';
    return `https://${host}:443/playground`;
  }

  function updateMicSecurityHint() {
    const hint = $('mic-https-hint');
    const text = $('mic-https-text');
    if (!hint || !text) return;
    const hasCapture = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    if (secureContext() && hasCapture) {
      hint.classList.add('hidden');
      return;
    }
    const httpsUrl = micHttpsUrl();
    const localUrl = `http://localhost:${location.port || 80}${location.pathname || '/playground'}`;
    text.innerHTML = `This page is not a secure context, so the browser blocks microphone capture. `
      + `Pick one: `
      + `<a class="font-bold underline" href="${httpsUrl}">${httpsUrl}</a> (HTTPS), `
      + `<a class="font-bold underline" href="${localUrl}">${localUrl}</a> (localhost is always secure), `
      + `or run <span class="font-mono font-bold">start-mic-browser.cmd</span> which starts Chrome/Edge with this origin treated as secure.`;
    hint.classList.remove('hidden');
  }

  function setMicDot(color) {
    const dot = $('mic-dot');
    dot.style.background = color;
    dot.style.boxShadow = color === '#10b981'
      ? '0 0 0 3px rgba(16,185,129,.14)'
      : color === '#ef4444' ? '0 0 0 3px rgba(239,68,68,.14)' : '0 0 0 3px rgba(148,163,184,.14)';
  }

  function updateSpeakingUI(on, label) {
    playing = on;
    $('speaking-status').textContent = label || (on ? 'Speaking…' : 'Idle');
    const dot = $('speaking-dot');
    dot.style.background = on ? '#8b5cf6' : '#cbd5e1';
    dot.style.boxShadow = on ? '0 0 0 3px rgba(139,92,246,.15)' : 'none';
    $('stop-btn').disabled = !on;
    $('interrupt-btn').disabled = !(session && session.status === 'active');
    $('err-barge').textContent = `${session?.state?.bargeIns || 0} logged`;
  }

  function updateSoundButton() {
    $('sound-toggle').innerHTML = soundOn
      ? `${Shell.icon('volume')} Sound on`
      : `${Shell.icon('volume-off')} Muted`;
    $('sound-toggle').classList.toggle('btn-primary', soundOn);
    $('sound-toggle').classList.toggle('btn-outline', !soundOn);
  }

  function renderMetrics() {
    const fmt = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)} ms`);
    $('m-stt').textContent = fmt(metrics.stt);
    $('m-llm-first').textContent = fmt(metrics.llmFirst);
    $('m-llm').textContent = fmt(metrics.llm);
    $('m-tts').textContent = fmt(metrics.tts);
    $('m-e2e').textContent = fmt(metrics.e2e);
    $('m-turns').textContent = session?.turnCount ?? metrics.turns;
    $('m-session').textContent = session ? session.status : 'idle';
  }

  function renderProviderStatus() {
    const caps = health?.capabilities || {};
    const sttReady = !!caps.deepgramStt;
    const ttsReady = !!caps.deepgramTts;
    const sttProvider = providers.find((p) => p.name === 'deepgram');
    const ttsProvider = providers.find((p) => p.name === 'deepgram-tts');
    const sttFailed = sttProvider?.status === 'error';
    const ttsFailed = ttsProvider?.status === 'error';

    $('err-stt-name').textContent = sttReady ? 'Deepgram Nova-2' : 'Browser Web Speech API';
    $('err-stt-sub').textContent = sttFailed
      ? 'Adapter test failed - browser fallback active'
      : (sttReady ? 'Server-side transcription, smart formatting' : 'Browser recognition only - no key configured');
    $('err-audio').textContent = sttFailed ? 'failed' : (sttReady ? 'connected' : 'fallback');
    $('err-audio').className = `pill ${sttFailed ? 'pill-red' : (sttReady ? 'pill-green' : 'pill-amber')}`;

    $('err-tts-name').textContent = ttsReady ? 'Deepgram Flux / Aura' : 'Browser Speech Synthesis';
    $('err-tts-sub').textContent = ttsFailed
      ? 'Adapter test failed - browser fallback active'
      : (ttsReady ? 'Server-side synthesis, Flux + Aura voices' : 'Local voices only - no key configured');
    $('err-provider').textContent = ttsFailed ? 'failed' : (ttsReady ? 'connected' : 'fallback');
    $('err-provider').className = `pill ${ttsFailed ? 'pill-red' : (ttsReady ? 'pill-green' : 'pill-amber')}`;

    $('err-engine').textContent = 'ready';
    $('err-engine').className = 'pill pill-green';

    const fallbacks = (sttReady ? 0 : 1) + (ttsReady ? 0 : 1);
    const failures = (sttFailed ? 1 : 0) + (ttsFailed ? 1 : 0);
    const summary = $('err-summary');
    if (!health) {
      summary.textContent = 'offline';
      summary.className = 'pill pill-red';
    } else if (failures) {
      summary.textContent = `${failures} failed`;
      summary.className = 'pill pill-red';
    } else if (fallbacks) {
      summary.textContent = `${fallbacks} fallback`;
      summary.className = 'pill pill-amber';
    } else {
      summary.textContent = 'all live';
      summary.className = 'pill pill-green';
    }
  }

  function agentSummary(a) {    if (!a) {
      return `<span class="chip text-amber-700">No agent selected</span><a href="/agents" class="text-[10px] font-semibold text-violet-600 hover:underline">Create one →</a>`;
    }
    const policy = a.transferPolicy || {};
    return [
      `<span class="chip">${UI.esc(a.voice)} • ${UI.esc(a.tone)} • ${UI.esc(a.language)}</span>`,
      `<span class="chip chip-mono">${UI.esc(a.sttProvider)} → ${UI.esc(a.llmProvider)} → ${UI.esc(a.ttsProvider)}</span>`,
      `<span class="chip ${policy.enabled === false ? 'text-amber-700' : ''}">transfer ${policy.enabled === false ? 'off' : (policy.requireConsent === false ? 'direct' : 'consent')}</span>`,
      `<span class="chip">max ${a.timeoutSettings?.maxTurns ?? 20} turns</span>`,
      `<span class="chip">silence ${a.timeoutSettings?.silenceTimeoutSec ?? 8}s</span>`,
      UI.statusPill(a.status),
    ].join('');
  }

  function selectAgent(id) {
    agent = agents.find((a) => a.id === id) || null;
    $('agent-summary').innerHTML = agentSummary(agent);
    $('err-silence').textContent = `${agent?.timeoutSettings?.silenceTimeoutSec ?? 8}s`;
    $('stage-current').textContent = 'Not started';
    if (!session) {
      $('user-input').placeholder = 'Start a session to enable text input…';
    }
  }

  async function loadAgents() {
    try {
      agents = await API.agents();
    } catch (err) {
      agents = [];
      UI.toast(err.message, 'error');
    }
    const select = $('agent-select');
    if (!agents.length) {
      select.innerHTML = '<option value="">No agents available — create one first</option>';
      select.disabled = true;
      $('start-btn').disabled = true;
      $('agent-summary').innerHTML = agentSummary(null);
      return;
    }
    select.disabled = false;
    select.innerHTML = agents.map((a) => `<option value="${a.id}" ${a.status === 'archived' ? 'disabled' : ''}>${UI.esc(a.name)}${a.status === 'archived' ? ' (archived)' : ` • v${a.version}`}</option>`).join('');
    const wanted = UI.getParam('agentId');
    const chosen = agents.find((a) => a.id === wanted)
      || agents.find((a) => a.status !== 'archived')
      || agents[0];
    if (chosen) {
      select.value = chosen.id;
      selectAgent(chosen.id);
    }
  }

  // ---- transcript / events ----------------------------------------------

  function bubbleHTML(turn, extra = '') {
    const isUser = turn.role === 'user';
    const meta = [
      turn.intent ? UI.esc(turn.intent) : '',
      turn.latencyMs ? `${Math.round(turn.latencyMs)} ms` : '',
      turn.ts ? UI.fmtTime(turn.ts) : '',
      extra,
    ].filter(Boolean).join(' • ');
    return `<div class="turn-row ${isUser ? 'turn-user' : 'turn-agent'}">
      <div class="turn-avatar">${isUser ? 'U' : 'A'}</div>
      <div class="min-w-0 max-w-[92%]">
        <div class="turn-bubble" style="white-space:pre-wrap">${UI.esc(turn.content)}</div>
        ${meta ? `<div class="turn-meta">${meta}</div>` : ''}
      </div>
    </div>`;
  }

  function renderTranscript(turns) {
    const list = turns || [];
    if (!list.length) {
      $('transcript').innerHTML = `<div class="py-8 text-center">
        <div class="text-[11px] font-bold text-slate-500">No turns yet</div>
        <div class="mt-1 text-[10px] text-slate-400">Start a session to hear the greeting, then type or speak.</div>
      </div>`;
    } else {
      $('transcript').innerHTML = list.map((t) => bubbleHTML(t)).join('');
      $('transcript').scrollTop = $('transcript').scrollHeight;
    }
    $('turn-count-pill').textContent = `${list.length} turn${list.length === 1 ? '' : 's'}`;
  }

  function appendBubble(role, content, meta = '') {
    const empty = $('transcript').querySelector('.py-8');
    if (empty) $('transcript').innerHTML = '';
    const turn = { role, content, intent: null, latencyMs: null, ts: new Date().toISOString() };
    $('transcript').insertAdjacentHTML('beforeend', bubbleHTML(turn, meta));
    $('transcript').scrollTop = $('transcript').scrollHeight;
    const count = $('transcript').querySelectorAll('.turn-row').length;
    $('turn-count-pill').textContent = `${count} turn${count === 1 ? '' : 's'}`;
    return $('transcript').lastElementChild;
  }

  function eventColor(type) {
    if (type === 'error') return '#ef4444';
    if (type === 'barge_in') return '#f59e0b';
    if (type === 'transfer_request') return '#8b5cf6';
    if (type === 'session_ended') return '#94a3b8';
    if (type === 'session_started' || type === 'greeting') return '#10b981';
    return '#3b82f6';
  }

  function eventSummary(ev) {
    const p = ev.payload || {};
    if (ev.type === 'error') return p.message || 'Session error';
    if (p.intent) return `${p.intent}${p.latencyMs ? ` • ${p.latencyMs} ms` : ''}`;
    if (p.reason) return p.reason;
    if (p.count !== undefined) return `count ${p.count}`;
    if (p.mode) return p.mode;
    if (p.consent !== undefined) return `consent ${p.consent}`;
    const keys = Object.keys(p);
    return keys.length ? JSON.stringify(p).slice(0, 90) : '';
  }

  function renderEvents(events) {
    const list = (events || []).slice(-40);
    $('event-count').textContent = String((events || []).length);
    if (!list.length) {
      $('event-list').innerHTML = `<div class="py-6 text-center text-[10px] text-slate-400">Events appear after the session starts.</div>`;
      return;
    }
    $('event-list').innerHTML = list.map((ev) => `<div class="event-row">
      <span class="event-dot" style="background:${eventColor(ev.type)}"></span>
      <div class="min-w-0 flex-1">
        <div class="event-type">${UI.esc(ev.type)}</div>
        <div class="truncate text-[9px] text-slate-500">${UI.esc(eventSummary(ev))}</div>
      </div>
      <span class="event-ts">${UI.fmtTime(ev.ts)}</span>
    </div>`).join('');
    $('event-list').scrollTop = $('event-list').scrollHeight;
  }

  function stageLabel(state) {
    const stage = state?.stage;
    if (!state || !stage || stage === 'start') return 'Greeting';
    if (stage === 'awaiting_zip') return 'Eligibility · ZIP';
    if (stage === 'awaiting_coverage') return 'Coverage';
    if (stage === 'awaiting_consent') return 'Transfer consent';
    if (stage === 'transferred') return 'Transferred (mock)';
    if (stage === 'done') return 'Eligibility complete';
    return stage;
  }

  function renderSession() {
    const active = session && session.status === 'active';
    $('session-value').textContent = session ? session.status.charAt(0).toUpperCase() + session.status.slice(1) : 'Idle';
    $('session-value').className = `text-[11px] font-extrabold ${active ? 'text-emerald-600' : 'text-slate-800'}`;
    $('session-sub').textContent = session
      ? `${UI.shortId(session.id)} • ${session.userInputMode} mode`
      : 'No session started';
    $('user-input').disabled = !active;
    $('send-btn').disabled = !active || busy;
    $('start-btn').disabled = !!active || !agent;
    $('end-btn').classList.toggle('hidden', !active);
    $('agent-select').disabled = !!active;
    if (active) $('user-input').placeholder = micOn ? 'Speak, or type your message…' : 'Type your message…';
    else if (session) $('user-input').placeholder = 'Session ended. Start a new session.';
    const barge = session?.state?.bargeIns || 0;
    $('bargein-value').textContent = barge;
    $('err-barge').textContent = `${barge} logged`;
    $('interrupt-btn').disabled = !active;
    $('replay-btn').disabled = !(session && session.turns && session.turns.filter((t) => t.role === 'assistant').length);
    $('stage-current').textContent = session ? stageLabel(session.state) : 'Not started';
    highlightStage(session?.state);
    $('m-session').textContent = session ? session.status : 'idle';
  }

  function highlightStage(state) {
    const ids = ['stage-greeting', 'stage-pricing', 'stage-zip', 'stage-coverage', 'stage-consent', 'stage-termination'];
    ids.forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.style.background = '';
      el.style.color = '';
      el.style.borderColor = '';
    });
    const stage = state?.stage;
    const target = stage === 'awaiting_zip' ? 'stage-zip'
      : stage === 'awaiting_coverage' ? 'stage-coverage'
        : stage === 'awaiting_consent' ? 'stage-consent'
          : stage === 'transferred' || state?.ended ? 'stage-termination'
            : 'stage-greeting';
    const el = $(target);
    if (el && state) {
      el.style.background = '#f5f3ff';
      el.style.color = '#6d28d9';
      el.style.borderColor = '#ddd6fe';
    }
  }

  async function refreshSession(renderTranscriptToo = false) {
    if (!session) return;
    try {
      const detail = await API.session(session.id);
      session = detail;
      if (renderTranscriptToo) renderTranscript(detail.turns);
      renderEvents(detail.events);
      renderSession();
      renderMetrics();
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  // ---- TTS ---------------------------------------------------------------

  function pickBrowserVoice() {
    if (!('speechSynthesis' in window)) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices.length) return null;
    const lang = (agent?.language || 'en-US').toLowerCase();
    const matching = voices.filter((v) => (v.lang || '').replace('_', '-').toLowerCase().startsWith(lang.slice(0, 2)));
    const prefs = {
      alloy: ['aria', 'jenny', 'google us english', 'samantha'],
      nova: ['zira', 'samantha', 'google uk english female'],
      onyx: ['guy', 'david', 'daniel'],
      rachel: ['samantha', 'aria'],
      adam: ['david', 'guy'],
      'aura-asteria-en': ['aria', 'jenny', 'samantha'],
      'aura-luna-en': ['zira', 'samantha'],
      'aura-stella-en': ['aria', 'google us english'],
      'aura-orion-en': ['guy', 'david'],
      'aura-arcas-en': ['daniel', 'david'],
    }[agent?.voice] || [];
    return matching.find((v) => prefs.some((p) => v.name.toLowerCase().includes(p)))
      || matching.find((v) => v.localService)
      || matching[0]
      || null;
  }

  function browserSpeech(text, started, onStart, finish) {
    if (!('speechSynthesis' in window)) {
      UI.toast('Speech synthesis is not available in this browser.', 'error');
      finish(false);
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = agent?.language || 'en-US';
    u.rate = Math.min(2, Math.max(0.5, (agent?.speakingRate || 100) / 100));
    u.pitch = 1;
    const voice = pickBrowserVoice();
    if (voice) u.voice = voice;
    let fired = false;
    u.onstart = () => {
      if (fired) return;
      fired = true;
      onStart?.(Math.round(performance.now() - started));
    };
    u.onend = () => finish(true);
    u.onerror = (event) => {
      if (event.error === 'interrupted' || event.error === 'canceled') finish(false);
      else { UI.toast(`Speech synthesis error: ${event.error || 'unknown'}`, 'error'); finish(false); }
    };
    try {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    } catch (err) {
      UI.toast(`TTS failed: ${err.message}`, 'error');
      finish(false);
    }
  }

  function playText(text, { onStart } = {}) {
    if (!soundOn || !text) return Promise.resolve(false);
    stopPlayback();
    stopRequested = false;
    const started = performance.now();
    updateSpeakingUI(true, 'Speaking…');

    return new Promise((resolve) => {
      let settled = false;
      const finish = (ok) => {
        if (settled) return;
        settled = true;
        playResolve = null;
        currentAudio = null;
        updateSpeakingUI(false, 'Idle');
        resolve(ok);
      };
      playResolve = finish;

      const fallback = () => {
        if (stopRequested) { finish(false); return; }
        browserSpeech(text, started, onStart, finish);
      };

      const useDeepgram = agent?.ttsProvider === 'deepgram-tts' && health?.capabilities?.deepgramTts;
      if (!useDeepgram) {
        fallback();
        return;
      }
      API.tts(text, agent.voice).then((blob) => {
        if (stopRequested) { finish(false); return; }
        const url = URL.createObjectURL(blob);
        currentAudioUrl = url;
        const audio = new Audio(url);
        currentAudio = audio;
        audio.playbackRate = Math.min(2, Math.max(0.5, (agent?.speakingRate || 100) / 100));
        audio.onplay = () => onStart?.(Math.round(performance.now() - started));
        audio.onended = () => { URL.revokeObjectURL(url); finish(true); };
        audio.onerror = () => {
          URL.revokeObjectURL(url);
          if (!fallbackNoted) {
            fallbackNoted = true;
            UI.toast('Deepgram audio failed — using the browser voice.', 'info');
          }
          fallback();
        };
        audio.play().catch(() => {
          URL.revokeObjectURL(url);
          fallback();
        });
      }).catch((err) => {
        if (!fallbackNoted) {
          fallbackNoted = true;
          UI.toast(`Cloud TTS unavailable (${err.message}) — using the browser voice.`, 'info');
        }
        fallback();
      });
    });
  }

  function stopPlayback() {
    stopRequested = true;
    if (currentAudio) {
      try { currentAudio.pause(); } catch { /* noop */ }
      currentAudio = null;
    }
    if (currentAudioUrl) {
      try { URL.revokeObjectURL(currentAudioUrl); } catch { /* noop */ }
      currentAudioUrl = null;
    }
    if ('speechSynthesis' in window) {
      try { window.speechSynthesis.cancel(); } catch { /* noop */ }
    }
    const resolve = playResolve;
    playResolve = null;
    if (resolve) resolve(false);
    updateSpeakingUI(false, 'Idle');
  }

  async function replay() {
    if (!session || !session.turns) return;
    const assistantTurns = session.turns.filter((t) => t.role === 'assistant');
    if (!assistantTurns.length) {
      UI.toast('No assistant turns to replay yet.', 'info');
      return;
    }
    if (!soundOn) {
      UI.toast('Sound is muted. Enable sound to replay.', 'info');
      return;
    }
    stopPlayback();
    const btn = $('replay-btn');
    btn.disabled = true;
    for (const turn of assistantTurns) {
      const ok = await playText(turn.content);
      if (!ok) break;
    }
    btn.disabled = false;
  }

  // ---- mic / STT ---------------------------------------------------------

  function recordButtonLabel() {
    return (health?.capabilities?.deepgramStt && agent?.sttProvider === 'deepgram')
      ? 'Record for Deepgram STT'
      : 'Record voice note';
  }

  function setMicUI() {
    $('mic-toggle').innerHTML = micOn
      ? `${Shell.icon('mic-off')} Disable mic`
      : `${Shell.icon('mic')} Enable mic`;
    $('mic-toggle').classList.toggle('btn-danger', micOn);
    $('mic-toggle').classList.toggle('btn-outline', !micOn);
    $('mic-status').textContent = micOn
      ? (sttAuto ? 'Mic live — speak, or type below' : 'Mic live — level only (STT off)')
      : 'Mic off — text mode is ready';
    setMicDot(micOn ? '#10b981' : '#94a3b8');
    $('audio-value').textContent = micOn ? 'Microphone live' : 'Not enabled';
    $('audio-sub').textContent = micOn
      ? (micStream?.getAudioTracks()[0]?.label || 'Default input')
      : 'Click Enable mic';
    $('err-mic').textContent = !secureContext() ? 'https needed' : (micOn ? 'granted' : 'text');
    $('err-mic').className = `pill ${!secureContext() ? 'pill-amber' : (micOn ? 'pill-green' : 'pill-gray')}`;
    $('err-mic-sub').textContent = !secureContext()
      ? 'Open the HTTPS address - browsers block the mic on plain HTTP'
      : (micOn ? 'Live capture - levels on the meter' : 'Text-only fallback stays available');
    $('stt-toggle').textContent = `STT: ${sttAuto ? 'Auto' : 'Off'}`;
    $('stt-toggle').className = `btn btn-xs ${sttAuto ? 'btn-primary' : 'btn-outline'}`;
    $('record-btn').classList.toggle('hidden', !micOn);
    $('record-btn').textContent = recordButtonLabel();
    if (session) renderSession();
  }

  async function enableMic() {
    if (!navigator.mediaDevices?.getUserMedia) {
      updateMicSecurityHint();
      UI.toast(secureContext()
        ? 'This browser does not expose microphone capture. Text mode remains available.'
        : 'Microphone needs a secure context - open the HTTPS address.', 'error');
      $('err-mic').textContent = secureContext() ? 'unsupported' : 'https needed';
      $('err-mic').className = 'pill pill-amber';
      $('err-mic-sub').textContent = secureContext()
        ? 'Browser exposes no microphone API - type instead'
        : 'Open the HTTPS address - browsers block the mic on plain HTTP';
      return;
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micOn = true;
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const loop = () => {
        if (!micOn || !analyser) return;
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i];
        const avg = sum / data.length;
        $('level-fill').style.width = `${Math.min(100, Math.round(avg * 1.9))}%`;
        levelRaf = requestAnimationFrame(loop);
      };
      loop();
      setMicUI();
      if (sttAuto) startRecognition();
      resetSilenceTimer();
      UI.toast('Microphone enabled — speak naturally.', 'success');
    } catch (err) {
      micOn = false;
      setMicUI();
      $('err-mic').textContent = 'denied';
      $('err-mic').className = 'pill pill-red';
      $('err-mic-sub').textContent = 'Permission refused - type instead';
      UI.toast(`Microphone unavailable: ${err.message}. Text mode remains active.`, 'error');
    }
  }

  function disableMic() {
    micOn = false;
    sttAuto = false;
    stopRecognition();
    stopRecording(true);
    cancelAnimationFrame(levelRaf);
    levelRaf = null;
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    micStream = null;
    if (audioCtx) { try { audioCtx.close(); } catch { /* noop */ } }
    audioCtx = null;
    analyser = null;
    $('level-fill').style.width = '0%';
    clearTimeout(silenceTimer);
    silenceTimer = null;
    setMicUI();
    sttAuto = true;
    $('stt-toggle').textContent = 'STT: Auto';
    $('stt-toggle').className = 'btn btn-xs btn-primary';
  }

  function startRecognition() {
    if (!SR) {
      $('record-btn').classList.remove('hidden');
      UI.toast('Browser STT is unavailable. Use “Record voice note” (server STT) or type.', 'info');
      return;
    }
    stopRecognition();
    try {
      recognition = new SR();
      recognition.lang = agent?.language || 'en-US';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => { recognitionActive = true; };
      recognition.onresult = (event) => {
        let interim = '';
        let final = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (result.isFinal) final += result[0].transcript;
          else interim += result[0].transcript;
        }
        if (interim) {
          $('user-input').value = interim;
          $('mic-status').textContent = `Heard: ${interim}`;
        }
        if (final.trim()) {
          const text = final.trim();
          const now = Date.now();
          if (text === lastFinal && now - lastFinalAt < 1600) return;
          lastFinal = text;
          lastFinalAt = now;
          $('user-input').value = text;
          $('mic-status').textContent = `Heard: “${text}”`;
          voiceHeardAt = performance.now();
          if (session && session.status === 'active') {
            setTimeout(() => {
              if (session?.status === 'active' && !busy) {
                sendMessage(text, { fromVoice: true, heardAt: voiceHeardAt });
              }
            }, 280);
          }
        }
      };
      recognition.onerror = (event) => {
        if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
          sttAuto = false;
          setMicUI();
          $('err-mic').textContent = 'blocked';
          $('err-mic').className = 'pill pill-red';
          $('err-mic-sub').textContent = 'Recognition blocked - type instead';
          UI.toast('Speech recognition permission was denied. Type instead.', 'error');
        } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
          $('mic-status').textContent = `STT: ${event.error}`;
        }
      };
      recognition.onend = () => {
        recognitionActive = false;
        if (micOn && sttAuto && recognition) {
          setTimeout(() => {
            if (micOn && sttAuto && recognition && !recognitionActive) {
              try { recognition.start(); } catch { /* already started */ }
            }
          }, 450);
        }
      };
      recognition.start();
    } catch (err) {
      UI.toast(`Could not start speech recognition: ${err.message}`, 'error');
    }
  }

  function stopRecognition() {
    if (recognition) {
      try { recognition.onend = null; recognition.stop(); } catch { /* noop */ }
      recognition = null;
    }
    recognitionActive = false;
  }

  function currentMimeType() {
    if (!window.MediaRecorder) return '';
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
    return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
  }

  function stopRecording(discard = false) {
    if (mediaRecorder && recording) {
      mediaRecorder._discard = discard;
      try { mediaRecorder.stop(); } catch { /* noop */ }
      recording = false;
    }
  }

  async function toggleRecording() {
    if (!micOn) {
      await enableMic();
      if (!micOn) return;
    }
    if (!window.MediaRecorder) {
      UI.toast('MediaRecorder is not available in this browser. Type your message.', 'error');
      return;
    }
    if (recording) {
      stopRecording(false);
      return;
    }
    // Server-side STT (Deepgram) is push-to-talk. Pause live browser
    // recognition so the same utterance is not sent twice.
    resumeRecognitionAfterClip = recognitionActive;
    if (recognitionActive) stopRecognition();
    const mimeType = currentMimeType();
    try {
      mediaRecorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);
    } catch (err) {
      UI.toast(`Recorder unavailable: ${err.message}`, 'error');
      return;
    }
    recordChunks = [];
    mediaRecorder.ondataavailable = (event) => { if (event.data.size) recordChunks.push(event.data); };
    mediaRecorder.onstop = async () => {
      recording = false;
      $('record-btn').textContent = recordButtonLabel();
      try {
        if (mediaRecorder?._discard) return;
        const blob = new Blob(recordChunks, { type: mimeType || 'audio/webm' });
        if (blob.size < 1000) {
          UI.toast('Recording was too short — try again.', 'info');
          return;
        }
        const started = performance.now();
        $('record-btn').disabled = true;
        const data = await API.stt(blob, session?.id);
        const text = (data.transcript || '').trim();
        if (!text) {
          UI.toast('No speech detected. Try again or type.', 'info');
          return;
        }
        $('user-input').value = text;
        voiceHeardAt = performance.now();
        if (session?.status === 'active') sendMessage(text, { fromVoice: true, heardAt: started });
        else UI.toast(`Heard: "${text}" (start a session to send)`, 'info');
      } catch (err) {
        UI.toast(`${err.message} - you can type instead.`, 'error');
        $('err-audio').textContent = 'fallback';
        $('err-audio').className = 'pill pill-amber';
        $('err-stt-sub').textContent = 'Transcription failed - type instead';
      } finally {
        $('record-btn').disabled = false;
        $('record-btn').textContent = recordButtonLabel();
        if (resumeRecognitionAfterClip && micOn && sttAuto) startRecognition();
        resumeRecognitionAfterClip = false;
      }
    };
    mediaRecorder.start();
    recording = true;
    $('record-btn').textContent = 'Stop & transcribe';
    UI.toast('Recording… press again to stop and transcribe.', 'info');
  }

  // ---- turns -------------------------------------------------------------

  function resetSilenceTimer() {
    clearTimeout(silenceTimer);
    silenceTimer = null;
    if (!micOn || !session || session.status !== 'active' || silencePrompted) return;
    const seconds = Math.max(1, agent?.timeoutSettings?.silenceTimeoutSec || 8);
    silenceTimer = setTimeout(() => {
      if (!micOn || !session || session.status !== 'active' || silencePrompted) return;
      if (playing) { resetSilenceTimer(); return; }
      silencePrompted = true;
      UI.toast(`Silence timeout (${seconds}s) — sending a clarification prompt.`, 'info');
      sendMessage('[silence]', { fromSilence: true });
    }, seconds * 1000);
  }

  async function sendMessage(text, opts = {}) {
    const content = String(text || '').trim();
    if (!content) return;
    if (!session || session.status !== 'active') {
      UI.toast('Start a session first.', 'error');
      return;
    }
    if (busy) return;
    busy = true;
    $('send-btn').disabled = true;
    $('user-input').disabled = true;
    $('mic-status').textContent = 'Processing turn…';
    if (playing) stopPlayback();
    if (!opts.fromSilence) {
      silencePrompted = false;
      lastFinal = '';
    }
    const t0 = performance.now();
    const heardAt = opts.heardAt || t0;
    appendBubble('user', content, opts.fromSilence ? 'silence timeout' : (opts.fromVoice ? 'voice' : ''));
    $('user-input').value = '';

    try {
      const res = await API.turn(session.id, content, opts.intent || null);
      const responseMs = Math.round(performance.now() - t0);
      metrics.stt = opts.fromVoice ? Math.max(0, Math.round(t0 - heardAt)) : 0;
      metrics.llmFirst = res.latencies?.llmFirstToken ?? res.latencies?.llm ?? responseMs;
      metrics.llm = res.latencies?.llm ?? responseMs;
      metrics.e2e = responseMs;
      appendBubble('assistant', res.assistantTurn.content, res.intent ? `${res.intent} • ${res.latencies?.llm ?? 0} ms` : '');
      session.status = res.sessionStatus;
      if (res.sessionStatus !== 'active') {
        $('user-input').disabled = true;
        $('send-btn').disabled = true;
        clearTimeout(silenceTimer);
        if (res.sessionStatus === 'error') {
          $('err-provider').textContent = 'error';
          $('err-provider').className = 'pill pill-red';
          $('err-tts-sub').textContent = 'Provider failure - session marked error';
          UI.toast(res.error || 'Provider failure surfaced safely.', 'error');
        } else {
          UI.toast('Session completed.', 'success', 2200);
        }
      }
      await refreshSession(false);
      renderMetrics();
      if (res.assistantTurn?.content) {
        playText(res.assistantTurn.content, {
          onStart: (ms) => {
            metrics.tts = ms;
            metrics.e2e = Math.round(performance.now() - t0);
            renderMetrics();
          },
        }).catch(() => {});
      }
      if (!opts.fromSilence) resetSilenceTimer();
    } catch (err) {
      const failed = appendBubble('assistant', `Turn failed: ${err.message}`, 'error');
      failed?.classList.add('border', 'border-red-200');
      UI.toast(err.message, 'error');
      $('mic-status').textContent = 'Turn failed — try again';
    } finally {
      busy = false;
      if (session?.status === 'active') {
        $('user-input').disabled = false;
        $('send-btn').disabled = false;
        $('user-input').focus();
      }
      $('mic-status').textContent = micOn ? 'Mic live — speak, or type below' : 'Mic off — text mode is ready';
      renderSession();
      renderMetrics();
    }
  }

  async function triggerInterrupt() {
    if (!session || session.status !== 'active') {
      UI.toast('Start a session first.', 'error');
      return;
    }
    if (busy) return;
    stopPlayback();
    busy = true;
    $('interrupt-btn').disabled = true;
    const marker = '[barge-in detected — playback stopped]';
    appendBubble('user', marker, 'barge-in');
    try {
      const res = await API.turn(session.id, marker, 'barge_in');
      appendBubble('assistant', res.assistantTurn.content, 'barge_in');
      metrics.llm = res.latencies?.llm || null;
      metrics.e2e = res.latencies?.e2e || null;
      await refreshSession(false);
      renderMetrics();
      UI.toast('Barge-in recorded — playback stopped.', 'success', 2200);
      if (res.assistantTurn?.content) {
        playText(res.assistantTurn.content).catch(() => {});
      }
    } catch (err) {
      UI.toast(err.message, 'error');
    } finally {
      busy = false;
      renderSession();
    }
  }

  // ---- session actions ---------------------------------------------------

  async function startSession() {
    if (!agent) {
      UI.toast('Select an agent first.', 'error');
      return;
    }
    if (session && session.status === 'active') {
      UI.toast('End the current session before starting a new one.', 'info');
      return;
    }
    const btn = $('start-btn');
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg> Starting…`;
    try {
      const detail = await API.createSession(agent.id, micOn ? 'voice' : 'text');
      session = detail;
      metrics = { stt: null, llmFirst: null, llm: null, tts: null, e2e: null, turns: 0 };
      silencePrompted = false;
      lastFinal = '';
      renderTranscript(detail.turns);
      renderEvents(detail.events);
      renderSession();
      renderMetrics();
      renderProviderStatus();
      if (detail.turns?.[0]?.content) {
        playText(detail.turns[0].content, {
          onStart: (ms) => {
            metrics.tts = ms;
            metrics.e2e = ms;
            renderMetrics();
          },
        }).catch(() => {});
      }
      resetSilenceTimer();
      $('user-input').focus();
      UI.toast('Session started — greeting is live.', 'success', 2200);
    } catch (err) {
      UI.toast(err.message, 'error');
      btn.disabled = false;
    } finally {
      btn.innerHTML = `${Shell.icon('play')} Start Session`;
      renderSession();
    }
  }

  async function endSession() {
    if (!session || session.status !== 'active') return;
    try {
      await API.patchSession(session.id, { status: 'completed', reason: 'user_ended' });
      stopPlayback();
      silencePrompted = true;
      clearTimeout(silenceTimer);
      session.status = 'completed';
      await refreshSession(true);
      UI.toast('Session ended and persisted.', 'success');
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  }

  // ---- wire up -----------------------------------------------------------

  $('start-btn').addEventListener('click', startSession);
  $('end-btn').addEventListener('click', endSession);
  $('send-form').addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage($('user-input').value);
  });
  $('quick-pills').addEventListener('click', (event) => {
    const btn = event.target.closest('[data-quick]');
    if (!btn) return;
    if (!session || session.status !== 'active') {
      UI.toast('Start a session first.', 'error');
      return;
    }
    sendMessage(btn.dataset.quick);
  });
  $('agent-select').addEventListener('change', (event) => selectAgent(event.target.value));
  $('mic-toggle').addEventListener('click', () => (micOn ? disableMic() : enableMic()));
  $('stt-toggle').addEventListener('click', () => {
    sttAuto = !sttAuto;
    if (sttAuto && micOn) startRecognition();
    else stopRecognition();
    setMicUI();
  });
  $('sound-toggle').addEventListener('click', () => {
    soundOn = !soundOn;
    localStorage.setItem('adriene:sound', soundOn ? 'on' : 'off');
    if (!soundOn) stopPlayback();
    updateSoundButton();
    UI.toast(soundOn ? 'Sound enabled' : 'Sound muted', 'info', 1500);
  });
  $('interrupt-btn').addEventListener('click', triggerInterrupt);
  $('replay-btn').addEventListener('click', replay);
  $('stop-btn').addEventListener('click', () => { stopPlayback(); UI.toast('Playback stopped.', 'info', 1500); });
  $('record-btn').addEventListener('click', toggleRecording);
  $('refresh-session').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    btn.classList.add('spin');
    await refreshSession(true);
    btn.classList.remove('spin');
    btn.disabled = false;
  });

  window.addEventListener('beforeunload', () => {
    stopPlayback();
    disableMic();
  });

  updateSoundButton();
  setMicUI();
  updateMicSecurityHint();
  renderMetrics();
  try {
    const [healthData, providerList] = await Promise.all([API.health(), API.providers()]);
    health = healthData;
    providers = providerList;
    $('connection-value').textContent = health.ok ? 'Connected' : 'Degraded';
    $('connection-sub').textContent = `localhost:${location.port || 80} • v${health.version}`;
    $('pg-api-pill').textContent = health.ok ? 'Local API' : 'API degraded';
    $('pg-api-pill').className = `pill ${health.ok ? 'pill-green' : 'pill-red'}`;
    $('err-silence').textContent = `${agent?.timeoutSettings?.silenceTimeoutSec ?? 8}s`;
    renderProviderStatus();
  } catch {
    $('connection-value').textContent = 'Offline';
    $('connection-sub').textContent = 'Start server.py';
    $('pg-api-pill').textContent = 'API offline';
    $('pg-api-pill').className = 'pill pill-red';
    renderProviderStatus();
  }

  await loadAgents();
})();

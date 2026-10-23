/* MMA BPO NEXUS — Stage 2 deterministic conversation and voice controller. */
'use strict';

const $ = (id) => document.getElementById(id);
const API_ROOT = '/api/v1';
const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;

let agent = null;
let session = null;
let sessions = [];
let voiceStatus = null;
let voiceCatalog = null;
let voicePreviewAudio = null;
let voicePreviewUrl = null;
let currentUser = null;
let csrfToken = null;
let previewBypass = false;
let authReady = false;
let teamUsers = [];
let busy = false;
let toastTimer = null;

let recognition = null;
let recognitionStartedAt = 0;
let recognitionRestartTimer = null;
let micWanted = false;
let mediaRecorder = null;
let mediaStream = null;
let recording = false;
let fluxSocket = null;
let fluxAudioContext = null;
let fluxSource = null;
let fluxNode = null;
let fluxMute = null;
let fluxStarting = false;
let fluxStartedAt = 0;
let fluxToken = 0;
let livekitStatus = null;
let lkRoom = null;
let lkJoinedRoom = '';
let lkAudioElements = new Map();

let soundOn = (() => {
  try { return localStorage.getItem('mma.nexus.sound') !== 'off'; } catch { return true; }
})();
let audioPlayer = null;
let audioUrl = null;
let playbackCancel = null;
let playbackToken = 0;
let ttsPlaying = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}

async function api(path, options = {}) {
  const request = { ...options, headers: { ...(options.headers || {}) } };
  const method = String(request.method || 'GET').toUpperCase();
  if (csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    request.headers['X-CSRF-Token'] = csrfToken;
  }
  if (request.body !== undefined) {
    request.headers['Content-Type'] = 'application/json';
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(API_ROOT + path, request);
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : { error: await response.text() };
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/auth/login') && !path.startsWith('/auth/setup')) showAuth('login');
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.details = data.details;
    throw error;
  }
  return data;
}

async function rawVoiceApi(path, body, contentType, responseType = 'json') {
  const response = await fetch(API_ROOT + path, {
    method: 'POST',
    headers: {
      'Content-Type': contentType,
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    body,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(data.error || `Voice request failed (${response.status})`);
    error.status = response.status;
    error.fallback = data.fallback;
    throw error;
  }
  if (responseType === 'blob') return { blob: await response.blob(), headers: response.headers };
  return response.json();
}

function showError(message) {
  $('global-error-text').textContent = message;
  $('global-error').classList.remove('hidden');
}

function clearError() {
  $('global-error').classList.add('hidden');
  $('global-error-text').textContent = '';
}

function toast(message, type = 'success') {
  clearTimeout(toastTimer);
  const element = $('toast');
  element.textContent = message;
  element.className = `toast${type === 'error' ? ' error' : ''}`;
  toastTimer = setTimeout(() => element.classList.add('hidden'), 4200);
}

function setConnection(online) {
  const status = $('connection-status');
  status.className = `connection ${online ? 'online' : 'offline'}`;
  status.replaceChildren(node('span', 'status-dot'), document.createTextNode(online ? ' API connected' : ' API offline'));
}

function isAdmin() {
  return Boolean(authReady && currentUser?.role === 'admin');
}

function showAuthError(message) {
  $('auth-error').textContent = message || '';
}

function showAuth(mode) {
  if (previewBypass && mode === 'login') return;
  stopAllVoice();
  authReady = false;
  currentUser = null;
  csrfToken = null;
  document.querySelector('.app-shell').inert = true;
  $('auth-screen').classList.remove('hidden');
  $('auth-loading').classList.add('hidden');
  $('setup-form').classList.toggle('hidden', mode !== 'setup');
  $('login-form').classList.toggle('hidden', mode !== 'login');
  showAuthError('');
  renderAccess();
}

function acceptAuth(data) {
  currentUser = data.user;
  csrfToken = data.csrfToken;
  previewBypass = data.previewBypass === true;
  authReady = true;
  document.querySelector('.app-shell').inert = false;
  $('auth-screen').classList.add('hidden');
  showAuthError('');
  renderAccess();
}

async function initializeAuth() {
  try {
    const status = await api('/auth/status');
    if (status.requiresSetup) {
      showAuth('setup');
      return;
    }
    if (!status.authenticated) {
      showAuth('login');
      return;
    }
    acceptAuth(status);
    await initialize();
  } catch (error) {
    document.querySelector('.app-shell').inert = true;
    $('auth-screen').classList.remove('hidden');
    $('setup-form').classList.add('hidden');
    $('login-form').classList.add('hidden');
    $('auth-loading').classList.remove('hidden');
    $('auth-loading').textContent = 'Unable to reach the secure application API.';
    showAuthError(error.message);
  }
}

function renderAccess() {
  const admin = isAdmin();
  $('user-name').textContent = currentUser?.displayName || '—';
  $('user-role').textContent = currentUser?.role || '—';
  $('logout-button').classList.toggle('hidden', previewBypass);
  $('read-only-banner').classList.toggle('hidden', admin);
  ['retention-section', 'team-section', 'audit-section', 'livekit-section'].forEach((id) => {
    $(id).classList.toggle('hidden', !admin);
  });
  document.querySelectorAll('#agent-form input, #agent-form select, #agent-form textarea, #retention-form input, #user-form input, #user-form select, #livekit-room').forEach((field) => {
    field.disabled = !admin || busy;
  });
  document.querySelectorAll('#retention-form button, #user-form button, #cleanup-retention, #refresh-audit').forEach((button) => {
    button.disabled = !admin || busy;
  });
}

function formatTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatLatency(value) {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number < 1000 ? `${number.toFixed(number < 10 ? 2 : 0)} ms` : `${(number / 1000).toFixed(2)} s`;
}

function shortId(value) {
  return value ? String(value).slice(0, 8) : '—';
}

function providerLabel(value) {
  return value === 'deepgram' ? 'Deepgram' : 'Browser';
}

function label(value) {
  const labels = {
    active: 'Active', completed: 'Completed', pending_transfer: 'Transfer pending',
    not_requested: 'Not requested', awaiting_consent: 'Awaiting consent',
    pending: 'Pending — not connected', blocked: 'Blocked by policy', declined: 'Declined',
    undetermined: 'Undetermined', preliminary_eligible: 'Preliminary review',
    manual_review: 'Manual review', not_assessed: 'Not assessed',
    account_holder_unconfirmed: 'Account unconfirmed', caller_ended: 'Caller ended',
    operator_ended: 'Operator ended', no_transfer: 'No transfer',
    consent_declined: 'Consent declined', max_turns: 'Turn limit reached',
    caller_input: 'Caller input', browser: 'Browser', deepgram: 'Deepgram',
    text: 'Text', 'browser-stt': 'Browser STT', 'deepgram-stt': 'Deepgram STT',
  };
  return labels[value] || String(value || '—').replaceAll('_', ' ');
}

function triState(value) {
  return value === true ? 'Yes' : value === false ? 'No' : '—';
}

function setStateValue(id, text, tone = '') {
  const element = $(id);
  element.textContent = text;
  element.className = tone ? `value-${tone}` : '';
}

function fillAgentForm() {
  if (!agent) return;
  $('agent-name').value = agent.name;
  $('agent-campaign').value = agent.campaign;
  $('agent-greeting').value = agent.greeting;
  $('persona-preset').value = agent.personaPreset || 'intake';
  $('agent-purpose').value = agent.purpose || 'Inbound service qualification';
  $('agent-tone').value = agent.tone || 'professional';
  $('stt-provider').value = agent.sttProvider;
  $('tts-provider').value = agent.ttsProvider;
  renderVoiceOptions();
  $('transfers-enabled').checked = agent.transfersEnabled;
  $('require-consent').checked = agent.requireConsent;
}

function renderVoiceOptions() {
  if (!voiceCatalog) return;
  const personaSelect = $('persona-preset');
  const currentPersona = personaSelect.value || agent?.personaPreset || 'intake';
  personaSelect.replaceChildren(...voiceCatalog.personaPresets.map((preset) => new Option(preset.label, preset.id)));
  personaSelect.value = currentPersona;

  const provider = $('stt-provider').value || agent?.sttProvider || 'browser';
  const currentModel = $('stt-model').value || agent?.sttModel || 'browser';
  const models = voiceCatalog.sttModels.filter((model) => model.provider === provider);
  $('stt-model').replaceChildren(...models.map((model) => new Option(model.label, model.id)));
  $('stt-model').value = models.some((model) => model.id === currentModel) ? currentModel : models[0]?.id || 'browser';

  const currentVoice = $('tts-voice').value || agent?.ttsVoice || 'aura-asteria-en';
  const groups = ['Flux', 'Aura'].map((family) => {
    const group = document.createElement('optgroup');
    group.label = `Deepgram ${family}`;
    voiceCatalog.ttsVoices.filter((voice) => voice.family === family).forEach((voice) => {
      group.appendChild(new Option(
        `${voice.name} · ${voice.accent} · ${voice.gender}`,
        voice.id,
      ));
    });
    return group;
  });
  $('tts-voice').replaceChildren(...groups);
  $('tts-voice').value = voiceCatalog.ttsVoices.some((voice) => voice.id === currentVoice)
    ? currentVoice : 'aura-asteria-en';
  $('tts-voice').disabled = $('tts-provider').value === 'browser' || !isAdmin() || busy;
  if (!voicePreviewAudio) {
    $('voice-preview-status').textContent = $('tts-provider').value === 'browser'
      ? 'Browser TTS uses an operating-system voice, not a Deepgram voice.'
      : voiceStatus?.deepgramConfigured
        ? 'Preview is optional. Account access is verified only by actual synthesis.'
        : 'Deepgram preview requires a server key. You can still save the voice selection.';
  }
}

function applyPersonaPreset() {
  const preset = voiceCatalog?.personaPresets.find((item) => item.id === $('persona-preset').value);
  if (!preset || preset.id === 'custom') return;
  $('agent-purpose').value = preset.purpose;
  $('agent-tone').value = preset.tone;
  $('agent-greeting').value = preset.greeting;
}

function stopVoicePreview(updateStatus = true) {
  if (voicePreviewAudio) {
    try { voicePreviewAudio.pause(); } catch { /* no-op */ }
  }
  if (voicePreviewUrl) URL.revokeObjectURL(voicePreviewUrl);
  voicePreviewAudio = null;
  voicePreviewUrl = null;
  $('stop-voice-preview').disabled = true;
  if (updateStatus) $('voice-preview-status').textContent = 'Voice preview stopped.';
}

async function previewSelectedVoice() {
  if (!isAdmin() || busy || !voiceCatalog) return;
  if ($('tts-provider').value === 'browser') {
    toast('Deepgram preview is not applicable to browser TTS.', 'error');
    return;
  }
  if (!voiceStatus?.deepgramConfigured) {
    toast('Deepgram preview requires a server-side API key.', 'error');
    return;
  }
  const voiceId = $('tts-voice').value;
  const voice = voiceCatalog.ttsVoices.find((item) => item.id === voiceId);
  if (!voice) return;
  stopVoicePreview(false);
  cancelPlayback(false);
  busy = true;
  renderControls();
  $('voice-preview-status').textContent = `Synthesizing ${voice.family} ${voice.name}…`;
  try {
    const text = `Hello, this is ${voice.name} from MMA BPO NEXUS. This is a voice preview.`;
    const { blob } = await rawVoiceApi('/voice/preview', JSON.stringify({ text, voice: voiceId }), 'application/json', 'blob');
    voicePreviewUrl = URL.createObjectURL(blob);
    voicePreviewAudio = new Audio(voicePreviewUrl);
    voicePreviewAudio.onended = () => {
      stopVoicePreview(false);
      $('voice-preview-status').textContent = `${voice.family} ${voice.name} preview finished · synthesis verified.`;
    };
    voicePreviewAudio.onerror = () => {
      stopVoicePreview(false);
      $('voice-preview-status').textContent = 'The browser could not play the synthesized audio.';
    };
    $('stop-voice-preview').disabled = false;
    $('voice-preview-status').textContent = `Playing ${voice.family} ${voice.name} · synthesis verified.`;
    await voicePreviewAudio.play();
  } catch (error) {
    stopVoicePreview(false);
    $('voice-preview-status').textContent = `Preview failed: ${error.message}`;
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

function renderAgentFacts() {
  $('metric-version').textContent = agent ? `Version ${agent.version}` : 'Version —';
  $('agent-version').textContent = agent ? `v${agent.version}` : 'v—';
  const configured = Boolean(voiceStatus?.deepgramConfigured);
  const config = $('deepgram-config-status');
  config.className = `voice-config-status ${configured ? 'configured' : 'unconfigured'}`;
  config.textContent = configured
    ? 'Deepgram key configured. Reachability is proven only by an actual STT/TTS request.'
    : 'Deepgram is not configured. Browser voice is active; cloud STT requires a server key.';
  $('metric-voice').textContent = agent
    ? `${providerLabel(agent.sttProvider)} STT · ${providerLabel(agent.ttsProvider)} TTS`
    : 'Browser by default';
  $('metric-voice-note').textContent = configured ? 'Deepgram configured · not assumed connected' : 'Deepgram not configured';
  if (voiceStatus?.disclosure) $('audio-disclosure').textContent = voiceStatus.disclosure;
}

function emptyTranscript() {
  const wrapper = node('div', 'empty-state');
  wrapper.append(
    node('span', 'empty-icon', '↗'),
    node('h3', '', 'Start with a clean session'),
    node('p', '', 'The agent will greet you, then verify the account holder before collecting any other information.'),
  );
  wrapper.querySelector('.empty-icon').setAttribute('aria-hidden', 'true');
  return wrapper;
}

function renderTranscript() {
  const transcript = $('transcript');
  if (!session || !(session.turns || []).length) {
    transcript.replaceChildren(emptyTranscript());
    return;
  }
  const rows = session.turns.map((turn) => {
    const article = node('article', `turn ${turn.role === 'user' ? 'user' : 'assistant'}`);
    const avatar = node('span', 'turn-avatar', turn.role === 'user' ? 'YOU' : 'AI');
    avatar.setAttribute('aria-hidden', 'true');
    const body = node('div', 'turn-body');
    body.appendChild(node('div', 'turn-bubble', turn.content));
    const details = [turn.role === 'user' ? 'Caller' : session.agentName, label(turn.intent)];
    if (turn.role === 'user' && turn.inputMethod && turn.inputMethod !== 'text') {
      details.push(label(turn.inputMethod));
      if (turn.sttLatencyMs !== null && turn.sttLatencyMs !== undefined) details.push(formatLatency(turn.sttLatencyMs));
    }
    if (turn.role === 'assistant' && turn.latencyMs > 0) details.push(`${formatLatency(turn.latencyMs)} policy`);
    details.push(formatTime(turn.createdAt));
    body.appendChild(node('div', 'turn-meta', details.join(' · ')));
    article.append(avatar, body);
    return article;
  });
  transcript.replaceChildren(...rows);
  transcript.scrollTop = transcript.scrollHeight;
}

function renderJourney() {
  const items = [...$('journey').querySelectorAll('li')];
  items.forEach((item) => { item.className = ''; });
  if (!session) return;
  const state = session.state || {};
  const currentByStage = {
    account_holder: 'account', zip: 'zip', coverage: 'coverage',
    transfer_offer: 'review', consent_pending: 'transfer', transfer_pending: 'transfer',
  };
  const current = currentByStage[state.stage];
  const order = ['account', 'zip', 'coverage', 'review', 'transfer'];
  const currentIndex = current ? order.indexOf(current) : -1;
  const captured = {
    account: state.accountHolder !== null && state.accountHolder !== undefined,
    zip: Boolean(state.zip),
    coverage: state.priorCoverage !== null && state.priorCoverage !== undefined,
    review: !['undetermined', 'not_assessed'].includes(state.eligibility),
    transfer: state.transferStatus === 'pending',
  };
  items.forEach((item, index) => {
    const step = item.dataset.step;
    if ((currentIndex >= 0 && index < currentIndex) || captured[step]) item.classList.add('done');
    if (step === current && session.status === 'active') item.classList.add('active');
    if (step === 'transfer' && state.transferStatus === 'pending') {
      item.classList.remove('done');
      item.classList.add('pending');
    }
  });
}

function latestVoiceRequest(operation) {
  if (!session) return null;
  return (session.voiceRequests || []).filter((row) => row.operation === operation).at(-1) || null;
}

function renderVoiceMetric(operation, elementId) {
  const record = latestVoiceRequest(operation);
  if (!record) {
    setStateValue(elementId, '—');
    return;
  }
  setStateValue(
    elementId,
    `${providerLabel(record.provider)} · ${formatLatency(record.latencyMs)} · ${record.status}`,
    record.status === 'error' ? 'negative' : 'positive',
  );
  const element = $(elementId);
  if (record.message) element.title = record.message;
}

function renderState() {
  if (!session) {
    setStateValue('state-account', '—');
    setStateValue('state-zip', '—');
    setStateValue('state-coverage', '—');
    setStateValue('state-eligibility', 'Undetermined');
    setStateValue('state-consent', '—');
    setStateValue('state-transfer', 'Not requested');
    setStateValue('state-outcome', 'In progress');
    setStateValue('voice-stt', '—');
    setStateValue('voice-tts', '—');
    $('event-count').textContent = '0 events';
    $('event-list').replaceChildren(node('p', 'muted-copy', 'Events will appear after a session starts.'));
    return;
  }
  const state = session.state || {};
  setStateValue('state-account', triState(state.accountHolder), state.accountHolder === true ? 'positive' : state.accountHolder === false ? 'negative' : '');
  setStateValue('state-zip', state.zip || '—', state.zip ? 'positive' : '');
  setStateValue('state-coverage', triState(state.priorCoverage), state.priorCoverage === true ? 'positive' : state.priorCoverage === false ? 'negative' : '');
  setStateValue('state-eligibility', label(state.eligibility), state.eligibility === 'preliminary_eligible' ? 'positive' : state.eligibility === 'manual_review' ? 'warning' : '');
  const consentText = state.consent !== null && state.consent !== undefined
    ? triState(state.consent)
    : session.policy && session.policy.requireConsent === false ? 'Not required' : '—';
  setStateValue('state-consent', consentText, state.consent === true ? 'positive' : state.consent === false ? 'negative' : '');
  setStateValue('state-transfer', label(state.transferStatus), state.transferStatus === 'pending' ? 'warning' : state.transferStatus === 'blocked' ? 'negative' : '');
  setStateValue('state-outcome', state.outcome ? label(state.outcome) : session.status === 'active' ? 'In progress' : label(session.status), state.outcome ? 'positive' : '');
  renderVoiceMetric('stt', 'voice-stt');
  renderVoiceMetric('tts', 'voice-tts');

  const events = session.events || [];
  $('event-count').textContent = `${events.length} event${events.length === 1 ? '' : 's'}`;
  if (!events.length) {
    $('event-list').replaceChildren(node('p', 'muted-copy', 'No events recorded.'));
    return;
  }
  const rows = events.slice(-8).reverse().map((event) => {
    const row = node('div', 'event-row');
    const top = node('div', 'event-top');
    top.append(
      node('span', 'event-type', event.type.replaceAll('_', ' ')),
      node('span', 'event-time', formatTime(event.createdAt)),
    );
    const payload = node('p', 'event-payload', JSON.stringify(event.payload || {}).slice(0, 150));
    row.append(top, payload);
    return row;
  });
  $('event-list').replaceChildren(...rows);
}

function renderHistory() {
  const select = $('session-history');
  const options = [new Option('Select a session to inspect', '')];
  const listed = [...sessions];
  if (session && !listed.some((item) => item.id === session.id)) listed.unshift(session);
  listed.forEach((item) => {
    options.push(new Option(`${shortId(item.id)} · ${label(item.status)} · ${formatTime(item.startedAt)}`, item.id));
  });
  select.replaceChildren(...options);
  select.value = session ? session.id : '';
  $('history-hint').textContent = listed.length
    ? `${listed.length} session${listed.length === 1 ? '' : 's'} available · persisted in SQLite`
    : 'Sessions persist across server restarts.';
}

function micSupportProblem() {
  if (!session || session.status !== 'active') return 'Start a session to enable voice';
  const provider = session.policy.sttProvider;
  if (provider === 'deepgram') {
    if (!voiceStatus?.deepgramConfigured) return 'Deepgram STT needs a server key · use text or a browser-STT contract';
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return 'MediaRecorder is unsupported · use text';
  } else if (provider === 'deepgram-flux') {
    if (!voiceStatus?.fluxConfigured) return 'Flux streaming needs a server key · use text or a browser-STT contract';
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !window.WebSocket) {
      return 'AudioWorklet streaming is unsupported · use text';
    }
  } else if (!SpeechRecognitionAPI) return 'Browser speech recognition is unsupported · use text';
  return '';
}

function renderCaptureStatus() {
  const host = $('capture-status');
  const text = $('capture-status-text');
  host.className = 'capture-status';
  if (fluxStarting) {
    host.classList.add('active');
    text.textContent = 'Opening the secure Flux stream…';
    return;
  }
  if (recording) {
    host.classList.add('recording');
    text.textContent = session?.policy.sttProvider === 'deepgram-flux'
      ? 'Streaming PCM16… waiting for the caller’s end of turn.'
      : 'Recording… click “Stop & transcribe” when finished.';
    return;
  }
  if (recognition) {
    host.classList.add('active');
    text.textContent = 'Listening… pause while the policy reply and TTS are processed.';
    return;
  }
  if (ttsPlaying) {
    host.classList.add('active');
    text.textContent = 'Playing the agent reply…';
    return;
  }
  const problem = micSupportProblem();
  text.textContent = session
    ? problem || `${providerLabel(session.policy.sttProvider)} STT ready · audio is not stored in SQLite`
    : 'Voice idle · text is always available';
}

function renderControls() {
  renderAccess();
  const active = session && session.status === 'active';
  const canConverse = Boolean(active && isAdmin());
  $('new-session').disabled = !isAdmin() || !agent || busy || Boolean(active);
  $('end-session').disabled = !canConverse || busy;
  $('turn-input').disabled = !canConverse || busy;
  $('send-turn').disabled = !canConverse || busy;
  $('save-agent').disabled = !isAdmin() || !agent || busy;
  $('refresh-data').disabled = busy;
  $('export-session').disabled = !session || busy;
  $('delete-session').disabled = !isAdmin() || !session || busy;
  $('preview-voice').disabled = !isAdmin() || busy || !voiceStatus?.deepgramConfigured || $('tts-provider').value === 'browser';
  $('stop-voice-preview').disabled = !voicePreviewAudio;
  $('sound-button').disabled = !session;
  $('replay-button').disabled = busy || !session || !(session.turns || []).some((turn) => turn.role === 'assistant');
  $('sound-button').textContent = soundOn ? 'Sound on' : 'Sound off';
  $('sound-button').classList.toggle('button-secondary', soundOn);
  $('sound-button').classList.toggle('button-quiet', !soundOn);

  const micProblem = micSupportProblem();
  $('mic-button').disabled = !canConverse || busy || fluxStarting || Boolean(micProblem);
  $('mic-button').classList.toggle('button-recording', recording || Boolean(recognition));
  $('mic-button').textContent = recording
    ? session?.policy.sttProvider === 'deepgram-flux' ? 'Stop stream' : 'Stop & transcribe'
    : recognition ? 'Disable mic'
      : session?.policy.sttProvider === 'deepgram' ? 'Record voice'
        : session?.policy.sttProvider === 'deepgram-flux' ? 'Start stream' : 'Enable mic';
  document.querySelectorAll('[data-message]').forEach((button) => { button.disabled = !canConverse || busy; });
  if (canConverse && !busy) $('turn-input').placeholder = 'Type here, or use the selected voice input…';
  else if (session && !isAdmin()) $('turn-input').placeholder = 'Read-only access: conversation writes are disabled.';
  else if (session) $('turn-input').placeholder = 'This session is closed. Start a new session to continue.';
  else $('turn-input').placeholder = 'Start a session to enable text input…';
  $('input-channel-label').textContent = session
    ? `${providerLabel(session.policy.sttProvider)} STT · ${providerLabel(session.policy.ttsProvider)} TTS · audio not stored`
    : 'Text + optional voice · deterministic policy';
  renderCaptureStatus();
  renderLiveKit();
}

function renderSessionHeader() {
  const status = $('session-status');
  if (!session) {
    status.textContent = 'Ready';
    status.className = 'session-status status-ready';
    $('session-meta').textContent = 'No session selected';
    return;
  }
  status.textContent = label(session.status);
  status.className = `session-status status-${session.status}`;
  $('session-meta').textContent = `${session.agentName} · contract v${session.agentVersion} · session ${shortId(session.id)} · ${session.turnCount} caller turns`;
}

function render() {
  renderAgentFacts();
  renderSessionHeader();
  renderControls();
  renderTranscript();
  renderJourney();
  renderState();
  renderHistory();
}

function rememberSession() {
  try {
    if (session) localStorage.setItem('mma.nexus.session', session.id);
    else localStorage.removeItem('mma.nexus.session');
  } catch { /* Storage is optional. */ }
}

async function refreshSessionList() {
  sessions = await api('/sessions?limit=50');
}

async function recordBrowserMetric(operation, status, latencyMs, message) {
  if (!isAdmin()) return;
  const sessionId = session?.id;
  if (!sessionId) return;
  try {
    const updated = await api(`/sessions/${encodeURIComponent(sessionId)}/voice-metrics`, {
      method: 'POST',
      body: { operation, status, latencyMs: Math.max(0, Math.min(120000, latencyMs)), message },
    });
    if (session?.id === sessionId) {
      session = updated;
      renderState();
    }
  } catch { /* A UI metric must never interrupt the conversation itself. */ }
}

function cancelPlayback(resume = true) {
  playbackToken += 1;
  const cancel = playbackCancel;
  playbackCancel = null;
  if (cancel) cancel();
  if (audioPlayer) {
    try { audioPlayer.pause(); } catch { /* no-op */ }
  }
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioPlayer = null;
  audioUrl = null;
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  ttsPlaying = false;
  if (resume) resumeMicrophone();
}

function playAudioBlob(blob, token) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      playbackCancel = null;
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      audioUrl = null;
      audioPlayer = null;
      if (error) reject(error); else resolve();
    };
    playbackCancel = () => finish();
    audioUrl = URL.createObjectURL(blob);
    audioPlayer = new Audio(audioUrl);
    audioPlayer.onended = () => finish();
    audioPlayer.onerror = () => finish(new Error('The browser could not play the synthesized audio'));
    audioPlayer.play().catch(finish);
    if (token !== playbackToken) finish();
  });
}

function speakWithBrowser(text) {
  return new Promise((resolve, reject) => {
    if (!('speechSynthesis' in window)) {
      reject(new Error('Browser speech synthesis is unavailable'));
      return;
    }
    const started = performance.now();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 1;
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      playbackCancel = null;
      if (error) {
        recordBrowserMetric('tts', 'error', performance.now() - started, error.message);
        reject(error);
      } else resolve();
    };
    playbackCancel = () => finish();
    utterance.onstart = () => {
      recordBrowserMetric('tts', 'success', performance.now() - started, 'Browser speech synthesis');
    };
    utterance.onend = () => finish();
    utterance.onerror = (event) => {
      if (event.error === 'canceled' || event.error === 'interrupted') finish();
      else finish(new Error(`Browser TTS failed: ${event.error || 'unknown error'}`));
    };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  });
}

async function deliverReply(text) {
  if (!soundOn || !text || !session) {
    resumeMicrophone();
    return;
  }
  cancelPlayback(false);
  const token = playbackToken;
  ttsPlaying = true;
  renderControls();
  try {
    if (session.policy.ttsProvider === 'deepgram' && voiceStatus?.deepgramConfigured) {
      try {
        const { blob } = await rawVoiceApi(
          `/voice/tts?sessionId=${encodeURIComponent(session.id)}`,
          JSON.stringify({ text }),
          'application/json',
          'blob',
        );
        if (token === playbackToken) await playAudioBlob(blob, token);
      } catch (error) {
        if (token !== playbackToken) return;
        toast(`Cloud TTS unavailable; using browser speech instead. ${error.message}`, 'error');
        await speakWithBrowser(text);
      }
    } else {
      await speakWithBrowser(text);
    }
  } catch (error) {
    if (token === playbackToken) toast(error.message, 'error');
  } finally {
    if (token === playbackToken) {
      ttsPlaying = false;
      renderControls();
      resumeMicrophone();
    }
  }
}

function resumeMicrophone() {
  clearTimeout(recognitionRestartTimer);
  if (!micWanted || busy || ttsPlaying || recognition || recording || fluxStarting || !session || session.status !== 'active') return;
  if (session.policy.sttProvider === 'deepgram-flux') {
    recognitionRestartTimer = setTimeout(() => {
      if (micWanted && !busy && !ttsPlaying && !recording && !fluxStarting) startFluxStream();
    }, 350);
    return;
  }
  if (session.policy.sttProvider !== 'browser') return;
  recognitionRestartTimer = setTimeout(() => {
    if (!recognition && micWanted && !busy && !ttsPlaying) startBrowserRecognition();
  }, 250);
}

function stopBrowserRecognition(keepWanted = false) {
  clearTimeout(recognitionRestartTimer);
  if (!keepWanted) micWanted = false;
  if (recognition) {
    const activeRecognition = recognition;
    recognition = null;
    try {
      activeRecognition.onend = null;
      activeRecognition.onresult = null;
      activeRecognition.onerror = null;
      activeRecognition.abort();
    } catch { /* already stopped */ }
  } else {
    recognition = null;
  }
  renderCaptureStatus();
}

function startBrowserRecognition() {
  if (!isAdmin()) return;
  if (!SpeechRecognitionAPI) {
    micWanted = false;
    toast('Browser speech recognition is unavailable. Text input remains available.', 'error');
    renderControls();
    return;
  }
  if (!session || session.status !== 'active' || busy || ttsPlaying || recognition) return;
  stopBrowserRecognition(true);
  recognition = new SpeechRecognitionAPI();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => {
    recognitionStartedAt = performance.now();
    renderCaptureStatus();
  };
  recognition.onresult = (event) => {
    let interim = '';
    let final = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result.isFinal) final += result[0].transcript;
      else interim += result[0].transcript;
    }
    if (interim) {
      $('turn-input').value = interim;
      $('character-count').textContent = `${interim.length} / 2000`;
    }
    const transcript = final.trim();
    if (transcript && session?.status === 'active' && !busy) {
      const elapsed = Math.max(0, Math.min(120000, performance.now() - recognitionStartedAt));
      stopBrowserRecognition(true);
      sendTurn(transcript, { inputMethod: 'browser-stt', sttLatencyMs: elapsed });
    }
  };
  recognition.onerror = (event) => {
    micWanted = false;
    if (!['aborted', 'no-speech'].includes(event.error)) {
      toast(`Speech recognition stopped: ${event.error}. Text input remains available.`, 'error');
    }
    stopBrowserRecognition(false);
    renderControls();
  };
  recognition.onend = () => {
    recognition = null;
    renderControls();
    resumeMicrophone();
  };
  try {
    recognition.start();
    micWanted = true;
    renderControls();
  } catch (error) {
    recognition = null;
    micWanted = false;
    toast(`Could not start speech recognition: ${error.message}`, 'error');
    renderControls();
  }
}

function currentMimeType() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

async function transcribeClip(blob) {
  busy = true;
  renderControls();
  let result = null;
  try {
    result = await rawVoiceApi(
      `/voice/stt?sessionId=${encodeURIComponent(session.id)}`,
      blob,
      blob.type || 'audio/webm',
    );
  } catch (error) {
    showError(`${error.message} You can continue by typing.`);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
  if (result?.transcript) {
    $('turn-input').value = result.transcript;
    $('character-count').textContent = `${result.transcript.length} / 2000`;
    await sendTurn(result.transcript, { inputMethod: 'deepgram-stt', sttLatencyMs: result.latencyMs });
  }
}

async function startDeepgramRecording() {
  if (!isAdmin() || !session || session.status !== 'active' || busy || recording) return;
  cancelPlayback(false);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    mediaStream = stream;
    const mimeType = currentMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    recorder._discard = false;
    mediaRecorder = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.onstop = () => {
      recording = false;
      stream.getTracks().forEach((track) => track.stop());
      if (mediaStream === stream) mediaStream = null;
      renderControls();
      if (recorder._discard) return;
      const blob = new Blob(chunks, { type: mimeType || 'audio/webm' });
      if (blob.size < 200) {
        toast('The recording was too short. Please try again.', 'error');
        return;
      }
      transcribeClip(blob);
    };
    recorder.start();
    recording = true;
    renderControls();
  } catch (error) {
    recording = false;
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
    toast(`Microphone unavailable: ${error.message}. Text input remains available.`, 'error');
    renderControls();
  }
}

function stopDeepgramRecording(discard = false) {
  if (mediaRecorder) {
    mediaRecorder._discard = discard;
    if (recording) {
      try { mediaRecorder.stop(); } catch { /* already stopped */ }
    }
  }
  if (mediaStream && !recording) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  recording = false;
  renderControls();
}

function cleanupFluxAudio() {
  try { fluxSource?.disconnect(); } catch { /* no-op */ }
  try { fluxNode?.disconnect(); } catch { /* no-op */ }
  try { fluxMute?.disconnect(); } catch { /* no-op */ }
  fluxSource = null;
  fluxNode = null;
  fluxMute = null;
  if (fluxAudioContext) {
    try { fluxAudioContext.close(); } catch { /* no-op */ }
  }
  fluxAudioContext = null;
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  mediaStream = null;
}

function stopFluxStream(discard = false) {
  if (discard) micWanted = false;
  fluxToken += 1;
  fluxStarting = false;
  recording = false;
  if (fluxSocket) {
    const socket = fluxSocket;
    fluxSocket = null;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try { socket.close(); } catch { /* already closed */ }
  }
  cleanupFluxAudio();
  renderControls();
}

function failFlux(error) {
  micWanted = false;
  stopFluxStream(true);
  toast(`${error.message}. Text input remains available.`, 'error');
}

async function startFluxStream() {
  if (!isAdmin() || !session || session.status !== 'active' || busy || recording || fluxStarting) return;
  const problem = micSupportProblem();
  if (problem) {
    toast(problem, 'error');
    renderControls();
    return;
  }
  micWanted = true;
  cancelPlayback(false);
  fluxStarting = true;
  const token = ++fluxToken;
  renderControls();
  try {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/api/v1/voice/stream?sessionId=${encodeURIComponent(session.id)}`);
    fluxSocket = socket;
    socket.binaryType = 'arraybuffer';
    socket.onopen = async () => {
      if (token !== fluxToken) { socket.close(); return; }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        mediaStream = stream;
        const Context = window.AudioContext || window.webkitAudioContext;
        fluxAudioContext = new Context();
        await fluxAudioContext.audioWorklet.addModule('/pcm-worklet.js');
        await fluxAudioContext.resume();
        fluxSource = fluxAudioContext.createMediaStreamSource(stream);
        fluxNode = new AudioWorkletNode(fluxAudioContext, 'pcm16-processor');
        fluxMute = fluxAudioContext.createGain();
        fluxMute.gain.value = 0;
        fluxNode.port.onmessage = (event) => {
          if (token === fluxToken && socket.readyState === WebSocket.OPEN) socket.send(event.data);
        };
        fluxSource.connect(fluxNode);
        fluxNode.connect(fluxMute);
        fluxMute.connect(fluxAudioContext.destination);
        fluxStartedAt = performance.now();
        fluxStarting = false;
        recording = true;
        renderControls();
      } catch (error) {
        failFlux(error);
      }
    };
    socket.onmessage = (event) => {
      if (token !== fluxToken) return;
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.event === 'error') {
        failFlux(new Error(data.error || 'Flux stream failed'));
        return;
      }
      const transcript = String(data.transcript || '').trim();
      if (transcript) {
        $('turn-input').value = transcript;
        $('character-count').textContent = `${transcript.length} / 2000`;
      }
      if (data.event === 'EndOfTurn' && transcript) {
        const elapsed = Math.max(0, Math.min(120000, performance.now() - fluxStartedAt));
        stopFluxStream(false);
        sendTurn(transcript, { inputMethod: 'deepgram-flux-stt', sttLatencyMs: elapsed });
      }
    };
    socket.onerror = () => {
      if (token === fluxToken) failFlux(new Error('Flux stream connection failed'));
    };
    socket.onclose = () => {
      if (token !== fluxToken) return;
      fluxStarting = false;
      recording = false;
      cleanupFluxAudio();
      renderControls();
      resumeMicrophone();
    };
  } catch (error) {
    failFlux(error);
  }
}

function stopAllVoice() {
  micWanted = false;
  stopBrowserRecognition(false);
  stopFluxStream(true);
  stopDeepgramRecording(true);
  stopVoicePreview(false);
  cancelPlayback(false);
  disconnectLiveKit();
  renderCaptureStatus();
}

function toggleMicrophone() {
  if (!isAdmin() || !session || session.status !== 'active' || busy) return;
  if (session.policy.sttProvider === 'deepgram-flux') {
    if (recording || fluxStarting) stopFluxStream(true);
    else {
      micWanted = true;
      startFluxStream();
    }
    return;
  }
  if (session.policy.sttProvider === 'deepgram') {
    if (recording) stopDeepgramRecording(false);
    else startDeepgramRecording();
  } else if (micWanted) {
    stopBrowserRecognition(false);
    renderControls();
  } else {
    micWanted = true;
    cancelPlayback(false);
    startBrowserRecognition();
  }
}

async function loadSession(sessionId, { staleOk = false } = {}) {
  stopAllVoice();
  try {
    session = await api(`/sessions/${encodeURIComponent(sessionId)}`);
    rememberSession();
    render();
    return true;
  } catch (error) {
    if (staleOk && error.status === 404) {
      session = null;
      rememberSession();
      return false;
    }
    throw error;
  }
}

async function startSession() {
  if (!isAdmin() || !agent || busy) return;
  stopAllVoice();
  busy = true;
  clearError();
  renderControls();
  let greeting = null;
  try {
    session = await api('/sessions', { method: 'POST', body: { agentId: agent.id } });
    greeting = session.turns?.[0]?.content || null;
    rememberSession();
    await Promise.all([refreshSessionList(), loadAudit()]);
    render();
    toast(`Session started with immutable contract v${session.agentVersion}.`);
    $('turn-input').focus();
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
  if (greeting) deliverReply(greeting);
}

async function sendTurn(content, voiceMeta = {}) {
  const text = String(content || '').trim();
  if (!isAdmin() || !text || !session || session.status !== 'active' || busy) return;
  if (session.policy.sttProvider === 'deepgram-flux') stopFluxStream(false);
  stopBrowserRecognition(true);
  busy = true;
  clearError();
  renderControls();
  let reply = null;
  try {
    session = await api(`/sessions/${encodeURIComponent(session.id)}/turns`, {
      method: 'POST',
      body: { content: text, ...voiceMeta },
    });
    reply = session.turns?.at(-1)?.content || null;
    $('turn-input').value = '';
    $('character-count').textContent = '0 / 2000';
    rememberSession();
    await refreshSessionList();
    if (session.status !== 'active') micWanted = false;
    render();
    if (session.status === 'active') $('turn-input').focus();
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
  if (reply) deliverReply(reply);
  else resumeMicrophone();
}

async function endSession() {
  if (!isAdmin() || !session || session.status !== 'active' || busy) return;
  stopAllVoice();
  busy = true;
  renderControls();
  try {
    session = await api(`/sessions/${encodeURIComponent(session.id)}/end`, { method: 'POST' });
    await Promise.all([refreshSessionList(), loadAudit()]);
    render();
    toast('Session ended and persisted.');
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

async function saveAgent(event) {
  event.preventDefault();
  if (!isAdmin() || !agent || busy || !$('agent-form').reportValidity()) return;
  busy = true;
  clearError();
  $('agent-form-status').textContent = '';
  renderControls();
  const sttProvider = $('stt-provider').value;
  const sttModel = $('stt-model').value;
  try {
    agent = await api(`/agent/${encodeURIComponent(agent.id)}`, {
      method: 'PUT',
      body: {
        name: $('agent-name').value,
        campaign: $('agent-campaign').value,
        greeting: $('agent-greeting').value,
        personaPreset: $('persona-preset').value,
        purpose: $('agent-purpose').value,
        tone: $('agent-tone').value,
        sttProvider,
        sttModel,
        ttsProvider: $('tts-provider').value,
        ttsVoice: $('tts-voice').value,
        transfersEnabled: $('transfers-enabled').checked,
        requireConsent: $('require-consent').checked,
      },
    });
    fillAgentForm();
    renderAgentFacts();
    await loadAudit();
    $('agent-form-status').textContent = `Saved immutable contract v${agent.version}.`;
    toast(session && session.status === 'active'
      ? `Contract v${agent.version} saved. This session remains on v${session.agentVersion}.`
      : `Agent saved as contract v${agent.version}.`);
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

async function refreshAll() {
  if (busy) return;
  busy = true;
  clearError();
  renderControls();
  try {
    const [nextAgent, nextVoiceStatus, nextCatalog] = await Promise.all([
      api('/agent'),
      api('/voice/status'),
      api('/voice/catalog'),
      refreshSessionList(),
      api('/health'),
    ]);
    agent = nextAgent;
    voiceStatus = nextVoiceStatus;
    voiceCatalog = nextCatalog;
    renderVoiceOptions();
    await Promise.all([loadRetention(), loadUsers(), loadAudit(), loadLiveKitStatus()]);
    if (session) await loadSession(session.id);
    setConnection(true);
    render();
    toast('Runtime data refreshed.');
  } catch (error) {
    setConnection(false);
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

function renderLiveKit() {
  const configured = Boolean(livekitStatus?.configured);
  const connected = livekitStatus?.connected === true;
  const host = $('livekit-status');
  host.className = `voice-config-status ${connected ? 'configured' : 'unconfigured'}`;
  host.textContent = !configured
    ? 'LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.'
    : connected
      ? `Connected · ${livekitStatus.host} · room list verified`
      : `Configured · ${livekitStatus.host || 'project'} · connectivity not verified`;
  const roomName = $('livekit-room').value.trim();
  $('livekit-create').disabled = !isAdmin() || !configured || busy || !roomName;
  $('livekit-join').disabled = !isAdmin() || !configured || busy || !roomName || Boolean(lkRoom);
  $('livekit-dispatch').disabled = !isAdmin() || !configured || busy || !roomName;
  $('livekit-verify').disabled = !isAdmin() || !configured || busy;
  $('livekit-leave').disabled = !lkRoom;
}

async function loadLiveKitStatus() {
  if (!isAdmin()) return;
  livekitStatus = await api('/livekit/status');
  renderLiveKit();
}

function livekitRoomName() {
  const name = $('livekit-room').value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(name)) {
    toast('Use 1-64 letters, numbers, underscores, or hyphens for the room name.', 'error');
    return '';
  }
  return name;
}

async function verifyLiveKit() {
  if (!isAdmin() || !livekitStatus?.configured || busy) return;
  busy = true;
  renderControls();
  try {
    const result = await api('/livekit/rooms');
    livekitStatus.connected = true;
    renderLiveKit();
    toast(`LiveKit connectivity verified · ${result.rooms.length} room(s).`);
  } catch (error) {
    livekitStatus.connected = false;
    renderLiveKit();
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

async function createLiveKitRoom() {
  const name = livekitRoomName();
  if (!name || busy) return;
  busy = true;
  renderControls();
  try {
    await api('/livekit/rooms', { method: 'POST', body: { name } });
    livekitStatus.connected = true;
    renderLiveKit();
    toast(`LiveKit room ${name} is ready.`);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

async function dispatchLiveKit() {
  const name = livekitRoomName();
  if (!name || busy) return;
  busy = true;
  renderControls();
  try {
    const result = await api('/livekit/dispatch', { method: 'POST', body: { room: name } });
    livekitStatus.connected = true;
    appendLiveKitTranscript('system', `Agent ${result.agentName} dispatched to ${name}`);
    toast(`Agent ${result.agentName} dispatched.`);
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

function appendLiveKitTranscript(who, text) {
  const host = $('livekit-transcript');
  if (host.querySelector('.muted-copy')) host.replaceChildren();
  const row = node('div', 'event-row');
  row.append(
    node('strong', 'event-type', `${who}: ${text}`),
    node('small', '', formatTime(new Date().toISOString())),
  );
  host.appendChild(row);
  while (host.children.length > 30) host.firstElementChild.remove();
  host.scrollTop = host.scrollHeight;
}

function renderLiveKitParticipants() {
  const host = $('livekit-participants');
  if (!lkRoom) {
    host.replaceChildren(node('p', 'muted-copy', 'Not connected.'));
    return;
  }
  const people = [...lkRoom.remoteParticipants.values()].map((participant) => ({
    identity: participant.identity,
    state: participant.isSpeaking ? 'speaking' : 'connected',
  }));
  people.push({ identity: lkRoom.localParticipant.identity, state: 'you · microphone on' });
  const rows = people.map((person) => {
    const row = node('div', 'user-row');
    row.append(node('strong', '', person.identity), node('small', '', person.state));
    return row;
  });
  host.replaceChildren(...rows);
}

async function joinLiveKit() {
  const name = livekitRoomName();
  if (!name || lkRoom || busy) return;
  if (!window.LivekitClient) {
    toast('The local LiveKit browser client did not load.', 'error');
    return;
  }
  busy = true;
  renderControls();
  try {
    const token = await api('/livekit/token', { method: 'POST', body: { room: name } });
    const { Room, RoomEvent, Track } = window.LivekitClient;
    const room = new Room({ adaptiveStream: true, dynacast: true });
    lkRoom = room;
    lkJoinedRoom = name;
    room.on(RoomEvent.TrackSubscribed, async (track) => {
      if (track.kind !== Track.Kind.Audio) return;
      try {
        const attached = track.attach();
        const element = attached && typeof attached.then === 'function' ? await attached : attached;
        if (element) {
          element.style.display = 'none';
          $('livekit-audio').appendChild(element);
          lkAudioElements.set(track.sid, element);
        }
      } catch (error) {
        appendLiveKitTranscript('system', `Audio attach failed: ${error.message}`);
      }
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      const element = lkAudioElements.get(track.sid);
      if (element) element.remove();
      lkAudioElements.delete(track.sid);
    });
    room.on(RoomEvent.ParticipantConnected, (participant) => {
      appendLiveKitTranscript('system', `${participant.identity} joined`);
      renderLiveKitParticipants();
    });
    room.on(RoomEvent.ParticipantDisconnected, (participant) => {
      appendLiveKitTranscript('system', `${participant.identity} left`);
      renderLiveKitParticipants();
    });
    room.on(RoomEvent.TranscriptionReceived, (transcription, participant) => {
      const text = transcription?.text || (Array.isArray(transcription) ? transcription.map((item) => item.text || '').join(' ') : '');
      if (text) appendLiveKitTranscript(participant?.identity || 'agent', text);
    });
    room.on(RoomEvent.Disconnected, () => {
      lkRoom = null;
      lkAudioElements.forEach((element) => element.remove());
      lkAudioElements.clear();
      renderLiveKitParticipants();
      renderLiveKit();
    });
    await room.connect(token.url, token.token);
    await room.localParticipant.setMicrophoneEnabled(true);
    livekitStatus.connected = true;
    appendLiveKitTranscript('system', `You joined ${name} with microphone audio`);
    renderLiveKitParticipants();
    renderLiveKit();
    toast(`Joined LiveKit room ${name}.`);
  } catch (error) {
    if (lkRoom) {
      try { await lkRoom.disconnect(); } catch { /* no-op */ }
      lkRoom = null;
    }
    toast(`${error.message}. Microphone permission and LiveKit connectivity are required.`, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

function disconnectLiveKit() {
  if (lkRoom) {
    const room = lkRoom;
    lkRoom = null;
    room.disconnect().catch(() => {});
  }
  lkJoinedRoom = '';
  lkAudioElements.forEach((element) => element.remove());
  lkAudioElements.clear();
  renderLiveKitParticipants();
  renderLiveKit();
}

async function leaveLiveKit() {
  disconnectLiveKit();
  toast('Left the LiveKit room. The room itself was not deleted.');
}

async function loadRetention() {
  if (!isAdmin()) return;
  const policy = await api('/auth/retention');
  $('retention-days').value = policy.transcriptDays;
  $('retention-auto').checked = policy.autoDelete;
}

function renderUsers() {
  const host = $('user-list');
  const rows = teamUsers.map((user) => {
    const row = node('div', 'user-row');
    const top = node('div', 'user-row-top');
    top.append(
      node('strong', '', `${user.displayName} · ${user.role}`),
      node('span', 'version-pill', user.active ? 'active' : 'disabled'),
    );
    const meta = node('small', '', `${user.username} · last login ${user.lastLoginAt ? formatTime(user.lastLoginAt) : 'never'}`);
    const actions = node('div', 'user-row-actions');
    const roleButton = node('button', 'text-button', user.role === 'admin' ? 'Make viewer' : 'Make admin');
    roleButton.type = 'button';
    roleButton.dataset.userId = user.id;
    roleButton.dataset.action = 'role';
    const activeButton = node('button', 'text-button', user.active ? 'Deactivate' : 'Activate');
    activeButton.type = 'button';
    activeButton.dataset.userId = user.id;
    activeButton.dataset.action = 'active';
    actions.append(roleButton, activeButton);
    row.append(top, meta, actions);
    return row;
  });
  if (!rows.length) rows.push(node('p', 'muted-copy', 'No operators found.'));
  host.replaceChildren(...rows);
}

async function loadUsers() {
  if (!isAdmin()) return;
  teamUsers = await api('/auth/users');
  renderUsers();
}

async function updateUserAccess(userId, action) {
  if (!isAdmin() || busy) return;
  const user = teamUsers.find((item) => item.id === userId);
  if (!user) return;
  busy = true;
  renderControls();
  try {
    await api(`/auth/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      body: action === 'role'
        ? { role: user.role === 'admin' ? 'viewer' : 'admin', active: user.active }
        : { role: user.role, active: !user.active },
    });
    await Promise.all([loadUsers(), loadAudit()]);
    toast('Operator access updated.');
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
}

async function loadAudit() {
  if (!isAdmin()) return;
  const rows = await api('/auth/audit?limit=12');
  const elements = rows.map((row) => {
    const element = node('div', 'audit-row');
    element.append(
      node('strong', '', row.action.replaceAll('_', ' ')),
      node('small', '', `${row.username || 'system'} · ${row.entityType} ${row.entityId || ''} · ${formatTime(row.createdAt)}`),
    );
    return element;
  });
  if (!elements.length) elements.push(node('p', 'muted-copy', 'No audit events yet.'));
  $('audit-list').replaceChildren(...elements);
}

async function initialize() {
  render();
  try {
    const [healthData, agentData, voiceData, catalogData] = await Promise.all([
      api('/health'),
      api('/agent'),
      api('/voice/status'),
      api('/voice/catalog'),
      refreshSessionList(),
    ]);
    if (!healthData.ok) throw new Error('Application health check failed');
    agent = agentData;
    voiceStatus = voiceData;
    voiceCatalog = catalogData;
    fillAgentForm();
    await Promise.all([loadRetention(), loadUsers(), loadAudit(), loadLiveKitStatus()]);
    setConnection(true);
    let savedId = null;
    try { savedId = localStorage.getItem('mma.nexus.session'); } catch { /* optional */ }
    const sessionId = savedId || sessions[0]?.id;
    if (sessionId) await loadSession(sessionId, { staleOk: true });
    render();
  } catch (error) {
    setConnection(false);
    showError(`Unable to initialize MMA BPO NEXUS: ${error.message}`);
    render();
  }
}

$('agent-form').addEventListener('submit', saveAgent);
$('new-session').addEventListener('click', startSession);
$('end-session').addEventListener('click', endSession);
$('mic-button').addEventListener('click', toggleMicrophone);
$('sound-button').addEventListener('click', () => {
  soundOn = !soundOn;
  try { localStorage.setItem('mma.nexus.sound', soundOn ? 'on' : 'off'); } catch { /* optional */ }
  if (!soundOn) cancelPlayback(true);
  renderControls();
});
$('replay-button').addEventListener('click', () => {
  const reply = session?.turns?.filter((turn) => turn.role === 'assistant').at(-1)?.content;
  if (!reply) return;
  if (!soundOn) {
    soundOn = true;
    try { localStorage.setItem('mma.nexus.sound', 'on'); } catch { /* optional */ }
  }
  renderControls();
  deliverReply(reply);
});
$('refresh-data').addEventListener('click', refreshAll);
$('dismiss-error').addEventListener('click', clearError);
$('turn-form').addEventListener('submit', (event) => {
  event.preventDefault();
  sendTurn($('turn-input').value);
});
$('turn-input').addEventListener('input', (event) => {
  $('character-count').textContent = `${event.target.value.length} / 2000`;
});
$('session-history').addEventListener('change', async (event) => {
  if (!event.target.value || busy) return;
  busy = true;
  clearError();
  renderControls();
  try {
    await loadSession(event.target.value);
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
});
document.querySelectorAll('[data-message]').forEach((button) => {
  button.addEventListener('click', () => sendTurn(button.dataset.message));
});
window.addEventListener('beforeunload', stopAllVoice);

$('setup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  showAuthError('');
  if ($('setup-password').value !== $('setup-confirm').value) {
    showAuthError('Passwords do not match.');
    return;
  }
  const button = event.target.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const data = await api('/auth/setup', {
      method: 'POST',
      body: {
        username: $('setup-username').value,
        displayName: $('setup-name').value,
        password: $('setup-password').value,
      },
    });
    acceptAuth(data);
    await initialize();
  } catch (error) {
    showAuthError(error.message);
  } finally {
    button.disabled = false;
  }
});

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  showAuthError('');
  const button = event.target.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: { username: $('login-username').value, password: $('login-password').value },
    });
    $('login-password').value = '';
    acceptAuth(data);
    await initialize();
  } catch (error) {
    showAuthError(error.message);
  } finally {
    button.disabled = false;
  }
});

$('logout-button').addEventListener('click', async () => {
  if (previewBypass) return;
  try {
    await api('/auth/logout', { method: 'POST' });
  } catch { /* Local logout still clears operator state. */ }
  stopAllVoice();
  agent = null;
  session = null;
  sessions = [];
  teamUsers = [];
  rememberSession();
  showAuth('login');
});

$('user-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!isAdmin() || busy || !event.target.reportValidity()) return;
  busy = true;
  clearError();
  renderControls();
  try {
    await api('/auth/users', {
      method: 'POST',
      body: {
        displayName: $('new-user-name').value,
        username: $('new-user-username').value,
        password: $('new-user-password').value,
        role: $('new-user-role').value,
      },
    });
    event.target.reset();
    await Promise.all([loadUsers(), loadAudit()]);
    toast('Operator account created.');
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
});

$('user-list').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-user-id]');
  if (button) updateUserAccess(button.dataset.userId, button.dataset.action);
});

$('retention-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!isAdmin() || busy) return;
  busy = true;
  clearError();
  renderControls();
  try {
    await api('/auth/retention', {
      method: 'PUT',
      body: { transcriptDays: Number($('retention-days').value), autoDelete: $('retention-auto').checked },
    });
    await Promise.all([loadRetention(), loadAudit()]);
    toast('Retention policy saved.');
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
});

$('cleanup-retention').addEventListener('click', async () => {
  if (!isAdmin() || busy) return;
  if (!window.confirm('Delete every session older than the configured retention period?')) return;
  busy = true;
  clearError();
  renderControls();
  try {
    const result = await api('/auth/retention/cleanup', { method: 'POST' });
    await Promise.all([refreshSessionList(), loadAudit()]);
    if (session) {
      try { await loadSession(session.id, { staleOk: true }); } catch { /* expired session removed */ }
    }
    render();
    toast(`Retention cleanup removed ${result.deletedSessions} expired session(s).`);
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
});

$('refresh-audit').addEventListener('click', async () => {
  if (!isAdmin()) return;
  try { await loadAudit(); } catch (error) { toast(error.message, 'error'); }
});

$('export-session').addEventListener('click', () => {
  if (!session) return;
  window.location.assign(`${API_ROOT}/sessions/${encodeURIComponent(session.id)}/export`);
});

$('delete-session').addEventListener('click', async () => {
  if (!isAdmin() || !session || busy) return;
  if (!window.confirm('Delete this session, its transcript, events, and voice evidence? This cannot be undone.')) return;
  busy = true;
  clearError();
  renderControls();
  try {
    const deletedId = session.id;
    await api(`/sessions/${encodeURIComponent(deletedId)}`, { method: 'DELETE' });
    session = null;
    rememberSession();
    await Promise.all([refreshSessionList(), loadAudit()]);
    render();
    toast('Session and related evidence deleted.');
  } catch (error) {
    showError(error.message);
    toast(error.message, 'error');
  } finally {
    busy = false;
    renderControls();
  }
});

$('persona-preset').addEventListener('change', applyPersonaPreset);
$('stt-provider').addEventListener('change', renderVoiceOptions);
$('tts-provider').addEventListener('change', renderVoiceOptions);
$('preview-voice').addEventListener('click', previewSelectedVoice);
$('stop-voice-preview').addEventListener('click', () => stopVoicePreview(true));

$('livekit-create').addEventListener('click', createLiveKitRoom);
$('livekit-join').addEventListener('click', joinLiveKit);
$('livekit-dispatch').addEventListener('click', dispatchLiveKit);
$('livekit-leave').addEventListener('click', leaveLiveKit);
$('livekit-verify').addEventListener('click', verifyLiveKit);
$('livekit-room').addEventListener('input', renderLiveKit);

initializeAuth();

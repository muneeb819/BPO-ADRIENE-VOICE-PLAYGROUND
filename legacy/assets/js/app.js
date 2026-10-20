/*
 * Adriene Voice Studio - application logic
 * Deepgram Aura TTS + live streaming STT, with browser speech fallback.
 */
'use strict';

const CONFIG = Object.assign({
    deepgramApiKey: '',
    defaultVoice: 'aura-asteria-en',
    sttUrl: 'wss://api.deepgram.com/v1/listen?model=nova-2&punctuate=true&interim_results=true&smart_format=true'
}, window.ADRIENE_CONFIG || {});

const DEEPGRAM_API_KEY = String(CONFIG.deepgramApiKey || '').trim();

let audioCtx = null;
let isCallActive = false;
let isMuted = false;
let isListening = false;
let deepgramSocket = null;
let mediaRecorder = null;
let micStream = null;
let callTimer = null;
let callSeconds = 0;
let animationFrame = null;
let currentAudio = null;
let toastTimer = null;

const speechSynth = window.speechSynthesis || null;

/* ------------------------------------------------------------------ */
/* BPO domain scenarios                                                */
/* ------------------------------------------------------------------ */
const scenarios = {
    'customer-support': {
        name: 'Technical Customer Support',
        prompt: 'You are Adriene, a helpful and concise tier-1 technical support AI voice agent for BPO Operations. Guide the caller through network diagnostics, account access resets, and service ticket logs.',
        greeting: 'Hello! Thank you for calling Technical Customer Support. My name is Adriene. How can I assist with your service today?'
    },
    'collections': {
        name: 'Outbound Payment & Collections',
        prompt: 'You are Adriene from Financial Account Services. Assist clients regarding account balance updates with compliance, empathy, and clarity.',
        greeting: 'Good day! This is Adriene calling from Financial Account Services regarding a brief update on your recent account balance.'
    },
    'lead-qual': {
        name: 'Enterprise SDR Lead Qualification',
        prompt: 'You are Adriene, an Enterprise Business SDR. Ask qualifying questions regarding team size, BPO infrastructure budget, and implementation timeline.',
        greeting: 'Hi there! This is Adriene from Enterprise Cloud Solutions. I am reaching out to see if your team is evaluating scalable BPO infrastructure this quarter.'
    },
    'custom': {
        name: 'Custom Agent Script',
        prompt: 'You are a custom AI voice agent configured for specialized BPO workflows.',
        greeting: 'Hello! This is Adriene AI. How can I assist you with your custom workflow today?'
    }
};

/* ------------------------------------------------------------------ */
/* Startup                                                             */
/* ------------------------------------------------------------------ */
window.addEventListener('DOMContentLoaded', () => {
    loadScenarioPreset(true);
    initWaveform();
    updateVoiceSelection();

    if (!DEEPGRAM_API_KEY) {
        setSpeechStatus('API key missing', true);
        const hint = document.getElementById('key-hint');
        if (hint) hint.textContent = 'not set';
        showToast('Add your Deepgram key in assets/js/config.js to enable cloud voice.');
    } else {
        const hint = document.getElementById('key-hint');
        if (hint) hint.textContent = '...' + DEEPGRAM_API_KEY.slice(-5);
    }
});

window.addEventListener('beforeunload', () => {
    stopDeepgramSTT();
    if (currentAudio) currentAudio.pause();
    if (speechSynth) speechSynth.cancel();
});

/* ------------------------------------------------------------------ */
/* Navigation                                                          */
/* ------------------------------------------------------------------ */
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active-tab'));

    const content = document.getElementById(`view-${tabId}`);
    const button = document.getElementById(`tab-${tabId}`);

    if (content) content.classList.remove('hidden');
    if (button) button.classList.add('active-tab');
}

/* ------------------------------------------------------------------ */
/* Sound effects                                                       */
/* ------------------------------------------------------------------ */
function playBeep(freq = 440, duration = 0.15, type = 'sine') {
    if (isMuted) return;
    try {
        if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx.state === 'suspended') audioCtx.resume();

        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.05, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);

        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch (err) {
        console.warn('Audio context unavailable:', err);
    }
}

/* ------------------------------------------------------------------ */
/* Voice settings                                                      */
/* ------------------------------------------------------------------ */
function updateVoiceSelection() {
    const select = document.getElementById('voice-select');
    if (!select) return;
    const text = select.options[select.selectedIndex]?.text || '';
    document.getElementById('selected-voice-gender').innerText = text.split(' ')[1] || 'Aura Model';
}

function updateAudioParams() {
    document.getElementById('val-pitch').innerText = document.getElementById('input-pitch').value;
    document.getElementById('val-rate').innerText = document.getElementById('input-rate').value;
}

function loadScenarioPreset(silent = false) {
    const key = document.getElementById('scenario-preset').value;
    const scenario = scenarios[key] || scenarios['customer-support'];
    document.getElementById('system-prompt').value = scenario.prompt;
    if (silent !== true) {
        showToast(`Loaded "${scenario.name}" scenario.`);
    }
}

function selectScenarioCard(scenarioKey) {
    switchTab('sandbox');
    const select = document.getElementById('scenario-preset');
    select.value = scenarioKey;
    loadScenarioPreset();
}

/* ------------------------------------------------------------------ */
/* Call lifecycle                                                      */
/* ------------------------------------------------------------------ */
function startVoiceTest() {
    if (isCallActive) return;
    isCallActive = true;
    playBeep(600, 0.2);

    document.getElementById('btn-start-call').disabled = true;
    document.getElementById('btn-stop-call').disabled = false;
    document.getElementById('status-indicator-ring').className = 'w-3.5 h-3.5 rounded-full bg-emerald-500 pulse-ring';
    document.getElementById('agent-status-title').innerText = 'Call Active (Connected)';
    document.getElementById('agent-status-sub').innerText = 'Adriene AI active via Deepgram Speech Synthesis';

    callSeconds = 0;
    document.getElementById('call-duration').innerText = '00:00';
    clearInterval(callTimer);
    callTimer = setInterval(() => {
        callSeconds++;
        const mins = String(Math.floor(callSeconds / 60)).padStart(2, '0');
        const secs = String(callSeconds % 60).padStart(2, '0');
        document.getElementById('call-duration').innerText = `${mins}:${secs}`;
    }, 1000);

    const scenarioKey = document.getElementById('scenario-preset').value;
    const greeting = (scenarios[scenarioKey] || scenarios['customer-support']).greeting;

    setTimeout(() => {
        if (!isCallActive) return;
        appendTranscript('Agent', greeting);
        speakAgentText(greeting);
    }, 500);

    showToast('Call connected to the speech engine.');
}

function stopVoiceTest() {
    if (!isCallActive) return;
    isCallActive = false;
    playBeep(300, 0.2);

    if (speechSynth) speechSynth.cancel();
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }
    stopDeepgramSTT();

    clearInterval(callTimer);
    callTimer = null;
    document.getElementById('btn-start-call').disabled = false;
    document.getElementById('btn-stop-call').disabled = true;
    document.getElementById('status-indicator-ring').className = 'w-3.5 h-3.5 rounded-full bg-slate-500';
    document.getElementById('agent-status-title').innerText = 'Agent Idle';
    document.getElementById('agent-status-sub').innerText = 'Ready for real-time speech test session';
    setSpeechStatus(DEEPGRAM_API_KEY ? 'Deepgram Active' : 'Browser TTS');

    showToast('Call ended.');
}

/* ------------------------------------------------------------------ */
/* Text to speech                                                      */
/* ------------------------------------------------------------------ */
function setSpeechStatus(text, warn = false) {
    const el = document.getElementById('speech-status');
    if (!el) return;
    el.innerText = text;
    el.classList.toggle('text-emerald-400', !warn);
    el.classList.toggle('text-amber-400', warn);
}

async function speakAgentText(text) {
    if (!text || isMuted || !isCallActive) return;

    if (speechSynth) speechSynth.cancel();
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }

    if (!DEEPGRAM_API_KEY) {
        speakWithBrowser(text);
        return;
    }

    const model = document.getElementById('voice-select').value || CONFIG.defaultVoice;
    setSpeechStatus('Generating Speech...');

    try {
        const response = await fetch(`https://api.deepgram.com/v1/speak?model=${encodeURIComponent(model)}`, {
            method: 'POST',
            headers: {
                'Authorization': `Token ${DEEPGRAM_API_KEY}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ text })
        });

        if (!response.ok) {
            throw new Error(`Deepgram TTS request failed: ${response.status} ${response.statusText}`);
        }

        const audioBlob = await response.blob();
        if (!isCallActive) return;

        const audioUrl = URL.createObjectURL(audioBlob);
        currentAudio = new Audio(audioUrl);
        currentAudio.onended = () => {
            URL.revokeObjectURL(audioUrl);
            currentAudio = null;
            setSpeechStatus('Deepgram Active');
        };

        setSpeechStatus('Speaking (Deepgram)...');
        try {
            await currentAudio.play();
        } catch (err) {
            URL.revokeObjectURL(audioUrl);
            throw err;
        }
    } catch (err) {
        console.warn('Deepgram TTS unavailable, using browser voice:', err);
        speakWithBrowser(text);
    }
}

function speakWithBrowser(text) {
    if (!speechSynth) {
        setSpeechStatus('TTS unavailable', true);
        return;
    }
    speechSynth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.pitch = parseFloat(document.getElementById('input-pitch').value);
    utterance.rate = parseFloat(document.getElementById('input-rate').value);
    utterance.onstart = () => setSpeechStatus('Speaking (browser)...');
    utterance.onend = () => setSpeechStatus(DEEPGRAM_API_KEY ? 'Deepgram Active' : 'Browser TTS');
    speechSynth.speak(utterance);
}

/* ------------------------------------------------------------------ */
/* Conversation                                                        */
/* ------------------------------------------------------------------ */
function handleKeyPress(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        sendUserMessage();
    }
}

function sendUserMessage() {
    const field = document.getElementById('user-input-field');
    const message = field.value.trim();
    if (!message) return;

    if (!isCallActive) startVoiceTest();

    appendTranscript('User', message);
    field.value = '';
    generateAgentResponse(message);
}

function generateAgentResponse(userMsg) {
    const textLower = userMsg.toLowerCase();
    let response;
    let sentiment = 'Neutral';
    let risk = 'Low';

    if (/(angry|cancel|manager|horrible|supervisor)/.test(textLower)) {
        sentiment = 'Negative / Frustrated';
        risk = 'High';
        response = 'I completely understand your concern. Let me prioritize your case and transfer you to an account supervisor right away.';
    } else if (/(price|cost|billing|pay)/.test(textLower)) {
        sentiment = 'Inquiring';
        response = 'I can certainly verify your billing details. Our enterprise BPO packages offer transparent SLAs and tier rates.';
    } else if (/(hello|hi|hey)/.test(textLower)) {
        sentiment = 'Positive';
        response = 'Hello! I am connected and ready. What specific inquiry can I resolve for you today?';
    } else if (/thank/.test(textLower)) {
        sentiment = 'Positive';
        response = 'You are very welcome! Is there anything else I can assist you with?';
    } else {
        response = `Understood. Regarding "${userMsg}", I have updated your support case log in real time.`;
    }

    document.getElementById('sentiment-badge').innerText = `Sentiment: ${sentiment}`;
    document.getElementById('metric-risk').innerText = risk;
    document.getElementById('metric-latency').innerText = `${Math.floor(Math.random() * 60 + 140)}ms`;
    document.getElementById('metric-confidence').innerText = `${(98.8 + Math.random() * 0.9).toFixed(1)}%`;

    setTimeout(() => {
        if (!isCallActive) return;
        appendTranscript('Agent', response);
        speakAgentText(response);
    }, 400);
}

function appendTranscript(sender, text) {
    const box = document.getElementById('transcript-box');

    if (box.children.length === 1 && box.children[0].classList.contains('italic')) {
        box.innerHTML = '';
    }

    const isAgent = sender === 'Agent';
    const msgEl = document.createElement('div');
    msgEl.className = `flex flex-col ${isAgent ? 'items-start' : 'items-end'}`;

    msgEl.innerHTML = `
        <div class="flex items-center space-x-1.5 mb-1">
            <span class="font-semibold text-[10px] ${isAgent ? 'text-blue-400' : 'text-emerald-400'}">${escapeHtml(sender)}</span>
            <span class="text-[9px] text-slate-500 font-mono">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
        </div>
        <div class="p-3 rounded-2xl max-w-[85%] leading-relaxed ${isAgent ? 'bg-slate-800/90 text-slate-200 border border-slate-700/80 rounded-tl-none shadow-sm' : 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-tr-none shadow-md'}">
            ${escapeHtml(text)}
        </div>
    `;

    box.appendChild(msgEl);
    box.scrollTop = box.scrollHeight;
}

function clearTranscript() {
    document.getElementById('transcript-box').innerHTML = `
        <div class="text-center text-slate-500 py-10 italic">
            Press "Start Call Test" or type a message below to test Deepgram TTS &amp; Speech Recognition.
        </div>
    `;
    showToast('Transcript cleared.');
}

/* ------------------------------------------------------------------ */
/* Speech to text (Deepgram streaming WebSocket)                       */
/* ------------------------------------------------------------------ */
async function startDeepgramSTT() {
    if (isListening) return;

    if (!isCallActive) {
        showToast('Start the call test before opening the microphone.');
        return;
    }
    if (!DEEPGRAM_API_KEY) {
        showToast('Add your Deepgram key in assets/js/config.js to enable live STT.');
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Microphone requires http://localhost or an HTTPS page.');
        return;
    }

    try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        console.error('Microphone access error:', err);
        showToast('Microphone access denied or unavailable.');
        return;
    }

    isListening = true;

    try {
        deepgramSocket = new WebSocket(CONFIG.sttUrl, ['token', DEEPGRAM_API_KEY]);
    } catch (err) {
        console.error('WebSocket error:', err);
        stopDeepgramSTT();
        showToast('Could not open the Deepgram stream.');
        return;
    }

    deepgramSocket.onopen = () => {
        document.getElementById('mic-icon').className = 'fa-solid fa-microphone-slash text-rose-400 animate-pulse';
        showToast('Live transcription active. Speak now...');

        const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
        const mimeType = candidates.find(type => window.MediaRecorder && MediaRecorder.isTypeSupported(type));

        try {
            mediaRecorder = new MediaRecorder(micStream, mimeType ? { mimeType } : undefined);
        } catch (err) {
            console.error('MediaRecorder error:', err);
            stopDeepgramSTT();
            showToast('This browser cannot record the microphone.');
            return;
        }

        mediaRecorder.addEventListener('dataavailable', event => {
            if (event.data.size > 0 && deepgramSocket && deepgramSocket.readyState === WebSocket.OPEN) {
                deepgramSocket.send(event.data);
            }
        });
        mediaRecorder.start(250);
    };

    deepgramSocket.onmessage = message => {
        const received = JSON.parse(message.data);
        const transcript = received.channel?.alternatives?.[0]?.transcript;
        if (transcript && received.is_final) {
            document.getElementById('user-input-field').value = transcript;
            sendUserMessage();
        }
    };

    deepgramSocket.onerror = event => {
        console.error('Deepgram WebSocket error:', event);
        showToast('Deepgram stream error. Check the network and API key.');
    };

    deepgramSocket.onclose = () => {
        if (isListening) {
            showToast('Live transcription disconnected.');
        }
        stopDeepgramSTT();
    };
}

function stopDeepgramSTT() {
    const wasListening = isListening;
    isListening = false;

    const icon = document.getElementById('mic-icon');
    if (icon) icon.className = 'fa-solid fa-microphone text-slate-300';

    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        try { mediaRecorder.stop(); } catch (err) { /* already stopped */ }
    }
    mediaRecorder = null;

    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }

    if (deepgramSocket) {
        const socket = deepgramSocket;
        deepgramSocket = null;
        if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
            socket.close();
        }
    }

    return wasListening;
}

function toggleMic() {
    if (isListening) {
        stopDeepgramSTT();
        showToast('Microphone muted.');
    } else {
        startDeepgramSTT();
    }
}

/* ------------------------------------------------------------------ */
/* Waveform                                                            */
/* ------------------------------------------------------------------ */
function initWaveform() {
    const canvas = document.getElementById('waveform-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let width = 0;
    let height = 0;

    function resize() {
        const dpr = window.devicePixelRatio || 1;
        width = canvas.clientWidth || 600;
        height = canvas.clientHeight || 96;
        canvas.width = Math.max(1, Math.round(width * dpr));
        canvas.height = Math.max(1, Math.round(height * dpr));
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    resize();
    window.addEventListener('resize', resize);

    let phase = 0;

    function draw() {
        ctx.clearRect(0, 0, width, height);
        const centerY = height / 2;

        ctx.beginPath();
        ctx.lineWidth = 2.5;
        ctx.strokeStyle = isCallActive ? '#3b82f6' : '#334155';

        for (let x = 0; x <= width; x++) {
            const envelope = Math.sin((x / Math.max(width, 1)) * Math.PI);
            const amplitude = isCallActive
                ? Math.sin(x * 0.03 + phase) * 20 * envelope
                : Math.sin(x * 0.01 + phase) * 2;
            const y = centerY + amplitude;
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }

        ctx.stroke();
        phase += isCallActive ? 0.15 : 0.02;
        animationFrame = requestAnimationFrame(draw);
    }

    draw();
}

/* ------------------------------------------------------------------ */
/* Global controls                                                     */
/* ------------------------------------------------------------------ */
function toggleGlobalMute() {
    isMuted = !isMuted;
    const btn = document.getElementById('btn-global-mute');

    if (isMuted) {
        btn.innerHTML = '<i class="fa-solid fa-volume-xmark text-rose-400"></i>';
        if (speechSynth) speechSynth.cancel();
        if (currentAudio) {
            currentAudio.pause();
            currentAudio = null;
        }
        showToast('Audio feedback muted');
    } else {
        btn.innerHTML = '<i class="fa-solid fa-volume-high text-slate-300"></i>';
        showToast('Audio feedback enabled');
    }
}

function exportStudioData() {
    const guardrails = {
        autoEscalation: document.getElementById('toggle-escalation').checked,
        sentimentAnalysis: document.getElementById('toggle-sentiment').checked,
        pciRedaction: document.getElementById('toggle-redaction').checked
    };

    const config = {
        agent: 'Adriene Enterprise AI Voice Agent',
        engine: 'Deepgram API Integrated',
        scenario: document.getElementById('scenario-preset').value,
        systemPrompt: document.getElementById('system-prompt').value,
        voiceParams: {
            model: document.getElementById('voice-select').value,
            pitch: document.getElementById('input-pitch').value,
            rate: document.getElementById('input-rate').value
        },
        guardrails,
        timestamp: new Date().toISOString()
    };

    const json = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(config, null, 2));
    const anchor = document.createElement('a');
    anchor.setAttribute('href', json);
    anchor.setAttribute('download', `adriene_agent_config_${Date.now()}.json`);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();

    showToast('Agent setup exported to JSON!');
}

function triggerQuickDeployment() {
    playBeep(800, 0.1);
    document.getElementById('deploy-modal').classList.remove('hidden');
}

function closeDeployModal() {
    document.getElementById('deploy-modal').classList.add('hidden');
}

function copyWebhook() {
    const input = document.querySelectorAll('#deploy-modal input')[0];
    if (!input) return;
    input.select();

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value)
            .then(() => showToast('Webhook URL copied to clipboard!'))
            .catch(() => showToast('Copy failed - the URL is selected, press Ctrl+C.'));
    } else {
        try {
            document.execCommand('copy');
            showToast('Webhook URL copied to clipboard!');
        } catch (err) {
            showToast('Copy failed - the URL is selected, press Ctrl+C.');
        }
    }
}

function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    document.getElementById('toast-msg').innerText = message;
    toast.classList.remove('translate-y-20', 'opacity-0', 'pointer-events-none');

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.add('translate-y-20', 'opacity-0', 'pointer-events-none');
    }, 3000);
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/* ------------------------------------------------------------------ */
/* Modal niceties                                                      */
/* ------------------------------------------------------------------ */
document.addEventListener('click', event => {
    const modal = document.getElementById('deploy-modal');
    if (modal && event.target === modal) closeDeployModal();
});

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeDeployModal();
});

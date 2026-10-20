# Adriene Voice Studio

Enterprise voice-agent studio for BPO workflows, built on the original
single-file prototype. Deepgram Aura TTS + streaming STT, with browser
speech synthesis as a fallback.

## Run it

Double-click **start.cmd** (Windows) or:

```bash
python server.py
```

Then open <http://localhost:8000>. The server opens the browser for you.
If port 8000 is already in use it picks the next free port (8001, 8002, ...)
and prints the real URL.

A local server is required, not just an option: browsers only allow
microphone access on `http://localhost` or HTTPS pages, never on `file://`.

Any static host works too (Netlify, GitHub Pages, S3, nginx). Only the
browser APIs need a secure context.

## Project layout

```
AdrieneVoiceStudio/
├── index.html              markup (Tailwind CDN, Font Awesome, Inter/JetBrains Mono)
├── assets/
│   ├── css/styles.css      glass panels, waveform pulse, scrollbars, range inputs
│   └── js/
│       ├── config.js       Deepgram key + endpoint settings
│       └── app.js          tabs, call flow, TTS, STT, transcript, export, deploy
├── server.py               zero-dependency dev server (no npm needed)
├── start.cmd               Windows launcher
└── README.md
```

## Features

- **Live voice sandbox** - start/end call, timer, animated waveform, transcript,
  sentiment badge, latency and accuracy telemetry.
- **Deepgram TTS** - five Aura voices, pitch/rate controls, automatic
  `SpeechSynthesis` fallback when the API is unreachable.
- **Live STT** - `getUserMedia` + `MediaRecorder` streamed to
  `wss://api.deepgram.com/v1/listen` using the `token` subprotocol.
- **Workflows** - technical support, collections, SDR lead qualification,
  custom script; each loads a prompt and greeting.
- **Telephony, analytics, compliance** - config surfaces from the prototype.
- **Export setup** - downloads the current persona, voice params and guardrails
  as JSON.
- **Deploy modal** - webhook/SIP values with clipboard copy and Escape-to-close.

## Configuration

Edit `assets/js/config.js`:

```js
window.ADRIENE_CONFIG = {
    deepgramApiKey: "...",
    defaultVoice: "aura-asteria-en",
    sttUrl: "wss://api.deepgram.com/v1/listen?model=nova-2&punctuate=true&interim_results=true&smart_format=true"
};
```

## Security note - read this

The Deepgram key is embedded in client-side JavaScript, exactly as in the
original file. That means **anyone who opens the site can read it**. The key
that came with the prototype should be treated as compromised:

1. Rotate it in the Deepgram console.
2. For production, put a tiny backend between the browser and Deepgram, e.g.
   `POST /api/tts` and `GET /api/stt-token`, so the real key stays server-side.
3. Restrict the key by project/role where Deepgram allows it.

## Known limits

- CDN assets (Tailwind, Font Awesome, Google Fonts) need internet access.
- STT in Safari/Firefox depends on `MediaRecorder` codec support; the app picks
  the first supported of `audio/webm;codecs=opus`, `audio/webm`, `audio/ogg`.
- The conversational replies are rule-based demo logic, not an LLM. Wire
  `generateAgentResponse()` to your own model endpoint when ready.
- Tailwind's CDN build prints a production warning in the console; compile
  Tailwind for a real deployment.

## Quick test checklist

1. `start.cmd` -> page loads at `http://localhost:8000`.
2. "Start Call Test" -> waveform animates, greeting appears and is spoken.
3. Type "I need to cancel my account" -> risk switches to High.
4. Mic button -> allow permission, speak, transcript fills automatically.
5. Tabs switch; Export downloads JSON; Deploy modal opens and copies the URL.

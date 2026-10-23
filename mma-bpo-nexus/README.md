# MMA BPO NEXUS

## Stage 4.1 — Persona & Voice Studio + Secure Conversation, Streaming, and LiveKit

A from-scratch, security-first BPO intake application with deterministic policy, versioned agent contracts, real browser and Deepgram voice paths, authenticated operators, enforced retention, and optional LiveKit room control.

The original repository is preserved separately. This project lives entirely in `mma-bpo-nexus/`.

## Implemented capabilities

### Deterministic conversation

- Account-holder verification before ZIP collection
- Explicit affirmative, negative, and unknown states
- Preliminary review versus manual review—never accidental final approval
- Consent-gated transfer requests
- Disabled-transfer enforcement
- Pending-only transfers without a live adapter
- No invented pricing or provider success
- Immutable agent versions bound to every session

### Persona and Deepgram voice selection

- Six persona presets: custom, inbound intake, customer support, sales qualification, healthcare scheduling, and financial services
- Editable role/purpose and five response tones; these affect approved wording only, never policy decisions
- Exact custom greetings remain versioned
- STT selection for browser, Nova-2, Nova-3, and Flux streaming
- **36 Flux voices and 5 Aura voices** with accent/gender labels
- Flux synthesis uses `/v2/speak`; Aura synthesis uses `/v1/speak`
- Optional real voice preview with independent playback and request metadata
- Catalogue options are not falsely marked as account-verified; availability is proven only by actual synthesis or transcription

### Voice

| Mode | Implementation |
|---|---|
| Browser STT | Browser speech recognition with interim text and pause/resume |
| Buffered Deepgram STT | Push-to-talk `MediaRecorder` to Nova-2 or Nova-3 |
| Flux streaming STT | Browser AudioWorklet → PCM16/16 kHz → authenticated backend WebSocket → Deepgram `/v2/listen` |
| Browser TTS | Browser speech synthesis with replay and measured playback start |
| Deepgram TTS | Aura Asteria with browser fallback on failure |

- `StartOfTurn` and `EndOfTurn` event handling for Flux
- End-of-turn-driven deterministic policy execution
- Stream cancellation/restart across replies and session changes
- Real STT/TTS latency and success/error evidence labeled by source
- Audio is **never stored in SQLite or project files**
- Clear browser/Deepgram audio-processing disclosure

### Secure operator access

- First-run administrator setup—**no default password**
- PBKDF2-SHA256 password hashing with per-user salts
- Opaque session cookies; only token hashes are stored server-side
- HttpOnly, Secure, SameSite=Strict cookies with eight-hour expiry
- Per-session CSRF tokens required for every mutation
- Admin and read-only viewer roles
- Last-active-admin protection
- Password-reset session invalidation
- Authentication rate limiting and origin checks
- Audit evidence for authentication, configuration, sessions, retention, and LiveKit actions
- Request correlation IDs

### Retention and evidence

- Configurable transcript retention from 1–365 days
- Optional automatic deletion on startup, hourly, and on demand
- Individual session deletion with cascaded transcript/event/voice evidence
- JSON session export
- SQLite backup verification
- Concurrent agent-update and turn-write regression tests

### Optional LiveKit

- Configuration status with no false “connected” claim
- Connectivity verified only by an actual room-list request
- Room list/create/delete
- Existing deployed-agent dispatch by name
- Room-scoped join tokens with a ten-minute lifetime
- Browser join/leave, microphone, remote audio, participants, and transcript events
- No deployment generator, secret-bearing downloads, or exposed project API secret

## Deliberate limits

- Real SIP/PSTN telephony is **not implemented**. Transfer records remain pending.
- Deepgram account administration, complete voice catalogues, and Deepgram-hosted persona synchronization are not implemented. Persona settings remain local and versioned.
- LiveKit worker creation/deployment is not included; dispatch targets an existing deployed agent.
- Live provider calls require valid credentials and were not exercised during local tests. Provider contracts are covered by mocks/fakes and real JWT payload validation.
- This is not a multi-tenant production identity service; operators share the installation’s conversation data according to their role.

## First run

1. Install and start the app.
2. Open the preview.
3. Create the initial administrator username and strong password.
4. Optionally create read-only viewer accounts from **Team access**.

```bash
cd mma-bpo-nexus
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python run.py --host 0.0.0.0 --port 8766
```

On Windows, use `.venv\Scripts\python.exe`.

Default binding is `127.0.0.1`; `0.0.0.0` is used only for the sandbox/LAN preview. Microphone capture requires HTTPS or localhost. Do not enter real customer data in the demonstration.

## Optional provider configuration

Configuration is read from the **process environment**, not automatically from a `.env` file. Restart after changing values.

### Deepgram

```bash
export DEEPGRAM_API_KEY="<new_server_side_secret>"
```

Required for buffered STT, Flux streaming, and Deepgram TTS. A Project ID or API key identifier is not a substitute for the secret. The previously exposed credential must not be reused.

### LiveKit

```bash
export LIVEKIT_URL="wss://your-project.livekit.cloud"
export LIVEKIT_API_KEY="<server_side_key>"
export LIVEKIT_API_SECRET="<server_side_secret>"
export LIVEKIT_AGENT_NAME="<existing_deployed_agent_name>"
```

`LIVEKIT_AGENT_NAME` is required only for dispatch. The LiveKit API secret never appears in browser responses; the room-scoped join token is intentionally returned for the current operator’s short-lived connection.

### Database

```bash
export NEXUS_DB_PATH="/absolute/path/to/nexus.db"
```

The default is the gitignored `data/nexus.db`. Existing Stage 1 and Stage 2 databases are migrated without replacement.

## Verification

```bash
cd mma-bpo-nexus/backend
../.venv/bin/python -m pytest
```

The suite currently contains **69 tests** covering:

- Pure policy and state transitions
- Agent/session version immutability
- Persistence and non-destructive migration
- Authentication, CSRF, roles, setup lockout, and password resets
- Retention, export, deletion, and backup verification
- Browser and server voice metadata
- Deepgram Nova and Aura request contracts with mocked transport
- Authenticated Flux PCM streaming and turn evidence
- LiveKit room lifecycle, dispatch, and unconfigured behavior
- Real LiveKit JWT scope and ten-minute expiry
- Concurrent agent updates and turn sequencing
- All 41 Deepgram voice IDs, persona persistence, and preview behavior
- Flux versus Aura synthesis endpoint selection

Frontend JavaScript, AudioWorklet, HTML ID/reference, CSP, asset, and live DOM initialization checks are also included in the verification workflow.

`.github/workflows/mma-bpo-nexus.yml` runs compilation, tests, frontend syntax checks, and dependency auditing without provider secrets. The local `pip-audit` run currently reports **No known vulnerabilities found**.

## Main API areas

| Area | Paths |
|---|---|
| Health/API identity | `/api/v1`, `/api/v1/health` |
| Authentication | `/api/v1/auth/status`, `/setup`, `/login`, `/logout`, `/me` |
| Users and audit | `/api/v1/auth/users`, `/api/v1/auth/audit` |
| Retention | `/api/v1/auth/retention`, `/retention/cleanup` |
| Agents | `/api/v1/agent`, `/agent/{id}`, `/agent/{id}/versions` |
| Sessions | `/api/v1/sessions`, `/sessions/{id}`, `/turns`, `/end`, `/export` |
| Voice | `/api/v1/voice/status`, `/catalog`, `/stt`, `/tts`, `/preview`, `/stream` |
| Browser voice evidence | `/api/v1/sessions/{id}/voice-metrics` |
| LiveKit | `/api/v1/livekit/status`, `/rooms`, `/token`, `/dispatch` |

FastAPI also exposes `/api/openapi.json`. Interactive documentation is disabled to keep the frontend self-hosted under its Content Security Policy.

## Project structure

```text
mma-bpo-nexus/
├── run.py
├── backend/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── app/
│   │   ├── main.py                 # App factory, auth/CSRF, security, request IDs
│   │   ├── db.py                   # Schema and non-destructive migrations
│   │   ├── schemas.py
│   │   ├── api/                    # Auth, sessions, voice, streaming, LiveKit
│   │   ├── domain/conversation.py  # Pure deterministic policy
│   │   ├── providers/              # Deepgram, Flux, LiveKit contracts
│   │   └── repositories/           # SQLite transactions, users, sessions, audit
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── pcm-worklet.js
│   └── vendor/livekit-client.umd.js
└── data/                            # Runtime only; gitignored
```

The codebase is now at its intended final integration boundary. Further work should focus on credentialed provider verification and production operations—not adding unverified features or claiming live telephony success.

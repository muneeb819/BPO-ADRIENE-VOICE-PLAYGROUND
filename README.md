# BPO Adriene — AI Voice Agent Playground

A local-first, Windows-first port of the BPO Adriene voice-agent playground. It covers agent design, a deterministic conversation engine, live browser voice, provider adapters, regression testing, analytics, security controls, mock telephony and delivery documentation.

**Repository:** <https://github.com/muneeb819/BPO-ADRIENE-VOICE-PLAYGROUND>

The runtime is deliberately small: **Python 3.12 standard library + SQLite + static HTML/CSS/vanilla JS**. There is no Docker, Postgres, Node build step or runtime npm dependency.

The whole product ships in **one dark theme** — navy surfaces (`#0a0e1a` → `#111827`), violet accent, light text — matching the Voice Lab control panel. No page ships a light variant.

---

## Quick start (Windows 11)

```powershell
git clone https://github.com/muneeb819/BPO-ADRIENE-VOICE-PLAYGROUND.git
Set-Location BPO-ADRIENE-VOICE-PLAYGROUND
.\start.cmd
```

`start.cmd` creates `.env` from `.env.example` when missing, verifies Python, starts the server on port 8000 (or the next free port) and opens the browser.

Manual start:

```powershell
Copy-Item .env.example .env
notepad .env
python server.py --port 8000
```

Useful flags:

```powershell
python server.py --port 8010 --no-open
```

Verify the backend:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

Expected shape: `{ ok: true, database: "SQLite", checks: { ... }, capabilities: { ... } }`.

---

## Deepgram configuration

Set the key **only** in the gitignored `.env`:

```dotenv
DEEPGRAM_API_KEY=your_rotated_key
```

This enables:

| Capability | Configuration |
|---|---|
| TTS | Deepgram Flux (`/v2/speak`) with Aura fallback; Voice Lab default `flux-brittany-en` |
| STT | Deepgram Nova-2, `en-US`, smart formatting |
| Voice models | 36 Flux voices plus 5 Aura voices, selectable in Voice Lab and Agent Studio |
| Demo persona | Adriene — warm, concise inbound intake specialist; existing demo uses Aura `aura-asteria-en`, new agents default to Flux Brittany |

The API and frontend only expose boolean capability flags such as `deepgramTts` and `deepgramStt`. The key is never returned by `/api/*`, written into HTML/JS, stored in `localStorage`, or included in logs. `.env` is also blocked by the static server and ignored by Git.

**Voice picker:** `Voice Lab → Live adapter smoke test — TTS` renders a grouped picker (Provider → Voice, `Flux` and `Aura` groups) in the same dark control-panel theme as *Voice Preview & Controls*. Flux voices are served from Deepgram `/v2/speak`, Aura voices from `/v1/speak`; the same catalogue is available in `Agent Studio → Voice`.

Two actions sit under the picker:

| Control | Behaviour |
|---|---|
| **Play** | Synthesizes the sample text with the selected voice and plays it (re-play is instant — the clip is cached) |
| **Save voice** | Writes the selected voice to the chosen agent (`PUT /api/agents/{id}`) and stores it in `ttsConfig.model`. The save creates a new agent version, so the change is versioned and reversible |

Restart the server after changing `.env`. Test the connection from **Voice Lab → Deepgram** or:

```powershell
$providers = Invoke-RestMethod http://localhost:8000/api/providers
$dg = $providers | Where-Object name -eq 'deepgram'
Invoke-RestMethod -Method Post "http://localhost:8000/api/providers/$($dg.id)/test"
```

Without a key, the playground still works in text mode and uses browser Speech Synthesis / Web Speech recognition.

---

## Pages

| Route | Purpose |
|---|---|
| `/` | Foundation status, architecture, live health snapshot, quick actions |
| `/agents` | Agent CRUD, persona, providers, tools, version history and rollback |
| `/playground` | Live voice session: mic → STT → deterministic rules → TTS, barge-in, latency |
| `/lab` | Provider catalogue, connection tests, Deepgram TTS/STT smoke tests, voice preview |
| `/testing` | Test cases, fixture seeding, regression runs, transcripts, JSON/CSV export |
| `/analytics` | Volume, intents, latency percentiles, provider mix, session inspector |
| `/security` | Secret posture, frontend scan, validation selftest, retention, cleanup |
| `/telephony` | Mock calls/transfers, correlation logs, live-dial safety gate |
| `/docs` | Windows launch guide, SQLite operations, feature inventory, live verification |

---

## Architecture

```text
Browser (static HTML/CSS/JS, local Tailwind Play build)
        │  same-origin JSON + audio
        ▼
server.py (ThreadingHTTPServer, API, validation, rate limiting, redaction)
        │
        ├── SQLite  data/adriene.db
        ├── Deepgram Flux / Aura TTS + Nova-2 STT (only when key present)
        └── deterministic rule engine (offline, no provider required)
```

### Backend

- `server.py` — HTTP server, routing, schema/migrations, seed data, deterministic engine, provider adapters, security, telephony mocks.
- `.env` — secrets and runtime toggles. Never served.
- `data/adriene.db` — agents, versions, sessions, turns, events, test cases/runs, telephony logs, policies, providers.

### Frontend

- `assets/css/app.css` — design system and all page-specific components.
- `assets/js/api.js` — API client, formatting, toasts, dialogs, download helpers.
- `assets/js/shell.js` — sidebar, mobile nav, icons and shared header/footer.
- `assets/js/page-*.js` — one controller per page.
- `assets/vendor/tailwind.js` and `assets/fonts/*` — local assets; the app does not depend on a CDN at runtime.

### Database tables

`agents`, `agent_versions`, `sessions`, `turns`, `events`, `providers`, `test_cases`, `test_runs`, `telephony_logs`, `policies`.

Schema creation is idempotent on startup. Existing data survives restarts.

---

## Core behaviour

1. A session is created against a specific agent.
2. Caller text (typed or transcribed) is evaluated by deterministic rules before any optional generation.
3. Required fields are collected in order: account-holder confirmation → ZIP → prior coverage.
4. Consent is mandatory before a transfer request; the backend is the authority on transfer availability.
5. Replies are spoken through the selected TTS provider, or browser Speech Synthesis when no key is configured.
6. Each turn records latency, intent and events; Analytics reads those stored events rather than inventing metrics.

### Transfer policy

`requireConsent: true` means a transfer request without explicit consent is refused with a safe error. Mock telephony remains available; **live SIP/PSTN is intentionally blocked** and `/api/telephony/enable` refuses activation in this build.

---

## API overview

Public, localhost-only by default:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | DB, storage, uptime, capability booleans |
| GET/POST | `/api/agents` | List/create agents |
| GET/PUT/DELETE | `/api/agents/{id}` | Detail/update/delete |
| POST | `/api/agents/{id}/duplicate` | Copy an agent |
| GET | `/api/agents/{id}/versions` | Version history |
| POST | `/api/agents/{id}/rollback` | Restore a version |
| GET/POST | `/api/sessions` | Session list/start |
| GET | `/api/sessions/{id}` | Session + turns + events |
| POST | `/api/sessions/{id}/turns` | Submit a caller turn |
| POST | `/api/sessions/{id}/end` | End session |
| GET | `/api/providers` | Provider catalogue (no secrets) |
| POST | `/api/providers/{id}/test` | Connection test |
| POST | `/api/tts` | Flux / Aura TTS proxy (max 1200 chars) |
| POST | `/api/stt` | Nova-2 STT proxy (audio ≤ 8 MB) |
| GET/POST | `/api/test-cases` | List/create cases |
| POST | `/api/test-cases/seed` | Seed nine fixtures |
| GET/POST | `/api/test-runs` | Regression history/run |
| GET | `/api/analytics/summary` | Aggregated metrics |
| GET | `/api/security/status` | Secret presence, scan, auth posture |
| POST | `/api/security/selftest` | Nine backend validation checks |
| GET/PUT | `/api/security/retention` | Retention policy |
| GET | `/api/telephony/logs` | Mock telephony events |
| POST | `/api/telephony/mock-call` | Simulate a call/transfer |
| POST | `/api/telephony/enable` | Deliberately refuses live dialing |
| DELETE | `/api/sessions` | Delete sessions, telephony logs and test runs |

Errors are JSON `{ "error": "..." }`. There are no stack traces in responses. Payload validation problems always return **400** (never 500) with an actionable message.

---

## Smoke tests (Python automation)

`smoke_test.py` drives the running app end-to-end the same way the browser does — health, all nine page routes, secret exposure, provider adapters, Deepgram Flux/Aura TTS, Nova-2 STT, agent CRUD + versioning, the playground session loop, the regression suite, the security selftest, mock telephony and analytics. Standard library only.

```powershell
python smoke_test.py                                   # http://127.0.0.1:8000
python smoke_test.py --base-url http://127.0.0.1:8010
python smoke_test.py --skip-live                       # skip provider network calls
python smoke_test.py --json smoke-report.json          # machine readable report
```

The runner prints a PASS/FAIL report per section, cleans up the temporary agent and session it creates, and exits non-zero if anything failed.

---

## Publish on IIS (LAN address)

`publish-iis.cmd` publishes the app on IIS and binds it to this machine's LAN address. It self-elevates (approve the UAC prompt) and is idempotent.

```powershell
.\publish-iis.cmd
.\publish-iis.cmd -Port 8088 -BindAddress 192.168.18.29
```

What it does:

1. Repairs the IIS config ACLs that block `appcmd` for non-elevated users.
2. Starts the Python backend on loopback (`127.0.0.1:8010`) if it is not already running.
3. Copies **only** the static front-end (`*.html`, `assets/`) to `C:\inetpub\AdrieneVoice` — no `.env`, no `data/`, no `.py`.
4. Writes a `web.config` that maps `/agents`, `/playground`, `/lab`, … to their pages and reverse-proxies `/api/*` to the local backend, with `nosniff`, `SAMEORIGIN` and `no-referrer` headers plus `.env`/`.py`/`.db` blocked.
5. Creates the IIS site + app pool, adds an inbound firewall rule and verifies every route over the LAN address.
6. Logs everything to `publish-iis.log`.

The backend keeps listening on loopback only, so the API is never exposed directly — IIS is the only public entry point.

**Self-healing:** IIS reverse-proxies to `127.0.0.1:8010`, so the site depends on the Python backend being alive. A scheduled task (`AdrienneVoiceBackend`) starts it at logon and re-checks it every 5 minutes; `watchdog-backend.ps1` restarts it automatically if it stops. Verified by a real crash test: killing the backend turned the site into `502`, and the watchdog restored `200` on every route within seconds.

**Live on this machine:**

| URL | Purpose |
|---|---|
| <https://192.168.18.29> | **Mic enabled** — secure context, native browser microphone |
| <http://192.168.18.29:8088> | Same app over plain HTTP (mic needs `start-mic-browser.cmd`) |
| <http://localhost:8088> | Local host — browsers always treat `localhost` as secure, so the mic works here too |

The HTTPS certificate is self-signed and trusted in `LocalMachine\Root` (no browser warning on this machine). Verified with the full smoke suite — **16/16 on every origin**:

```powershell
python smoke_test.py --base-url https://192.168.18.29        # 16/16
python smoke_test.py --base-url http://192.168.18.29:8088    # 16/16
python smoke_test.py --base-url http://localhost:8088         # 16/16
```

---

## Microphone (mic) capture

Browsers only expose `navigator.mediaDevices.getUserMedia` in a **secure context** — HTTPS, or HTTP on `localhost`. Three ways to get a working mic:

| Option | Command / URL | Notes |
|---|---|---|
| **HTTPS (recommended)** | <https://192.168.18.29/playground> | Live now — self-signed certificate trusted in `LocalMachine\Root`, so the mic works in any browser with no extra flags |
| Local host | <http://localhost:8088/playground> | Browsers always treat `localhost` as secure — no setup, no admin rights |
| LAN IP over HTTP | `start-mic-browser.cmd` | Starts Chrome/Edge with `--unsafely-treat-insecure-origin-as-secure=http://192.168.18.29:8088` in a dedicated profile |

The app detects the situation instead of failing silently: the Microphone panel shows an amber banner with the exact URLs, and the *Provider status & fallbacks* card reports `https needed` for the microphone row while the STT/TTS adapters stay `connected`.

---

## Data, backup and reset

Stop the server before copying the database.

```powershell
# Backup
Copy-Item data\adriene.db data\adriene-backup.db

# Restore
Copy-Item data\adriene-backup.db data\adriene.db
```

To reset all runtime data, stop the server and delete `data\adriene.db`; it is recreated and reseeded on next start. For a selective cleanup use **Security → Delete Artifacts** (sessions, telephony logs, test runs).

---

## Security model

- Provider keys live only in backend environment variables.
- `.env`, `data/`, `*.db`, logs and Python caches are gitignored; the static handler rejects `.env`, `server.py`, database files and dotfiles.
- Frontend bundle scan is available at `/api/security/status` and in the Security page.
- Request validation limits names, instructions, speaking rate, timeouts, turn length and audio size.
- Per-client sliding-window rate limiting applies to `/api/*`.
- `AUTH_ENABLED=true` + `AUTH_SECRET=...` enables a Bearer-token gate before network exposure.
- No wildcard CORS. Same-origin by design.
- Telephony is mock-only; the live-enable endpoint always refuses.

**If a key has ever been pasted into chat, logs or source control, rotate it with the provider.** A key that appeared in the old `legacy/` build should be considered burned even if the current build only reads `.env`.

---

## Local QA

Recommended final pass:

1. `python -m py_compile server.py`
2. `/api/health` returns 200 JSON with `ok: true`.
3. `/security` → **Run Authorization & Validation Tests** → 9/9.
4. `/testing` → **Seed Fixtures** → **Run Regression Suite** → inspect transcripts.
5. `/playground` → start a session, speak/type a pricing question, confirm audio and latency.
6. `/lab` → test Deepgram TTS + STT.
7. `/analytics` → set a 24h filter and inspect a session.
8. `/telephony` → run a mock call; confirm live enable is blocked.
9. `/docs` → **Run live verification**.
10. Resize to mobile width and confirm navigation, cards and tables remain usable.

---

## Limitations

- Windows 11 / PowerShell workflow; Python 3.12 is recommended.
- Deepgram requires network access and a valid backend key. Network failures surface as actionable errors.
- Real telephony (SIP/VICIdial) is **not implemented**. It needs an authorised test environment, consent handling and an adapter.
- Token-cost estimation is intentionally unavailable; no reliable pricing source is configured.
- Browser microphone access requires `localhost` or HTTPS. If denied, use text input.
- Browser speech voices vary by operating system.
- The project is local-first. Do not expose it to a network without enabling auth and reviewing the security posture.
- The local UI uses a vendored Tailwind Play build; this is a local-first convenience, not a production CDN deployment.

---

## Troubleshooting

**Port already in use** — the server automatically tries the next free port; read the console URL. Or pass `--port`.

**`DEEPGRAM_API_KEY` shows as missing** — `.env` must be in the project root; restart the server after editing. Visit `/api/health` and check `capabilities.deepgramTts`.

**No microphone** — allow microphone permission in Chrome/Edge; use `localhost`, not a LAN IP; fall back to typed turns.

**No audio** — check the selected provider in Voice Lab. With no TTS key the browser voice is used; autoplay policies may require a click first.

**Database locked** — stop duplicate server processes, then restart. SQLite is single-file; avoid copying it while the server is running.

**Provider test fails** — the response includes the provider HTTP status or a network error message. Missing keys are reported as missing, not silently replaced with demo data.

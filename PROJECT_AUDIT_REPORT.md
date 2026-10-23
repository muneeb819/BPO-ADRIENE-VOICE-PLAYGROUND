# BPO Nexus / Adriene Voice Playground
## Whole-Project Audit & Inspection Report

**Audit date:** 2026-10-22 (UTC)
**Audited commit:** `a773da6ea2273ce541c5dd23e709a27d83cf3b2e`
**Branch:** `arena/27be84c0-bpo-adriene-voice-playground`
**Scope:** 90 tracked files, including the Python backend, first-party JavaScript, HTML/CSS, marketing and legacy applications, Windows/IIS scripts, smoke automation, configuration, documentation, vendored browser code, fonts, and brand assets.

---

## 1. Executive verdict

### **NO-GO for LAN or production deployment in the current state**

The repository is a broad, thoughtfully packaged **local prototype** with a small operational footprint, good static assets, and working basic CRUD/session flows. It is not yet a trustworthy production voice-agent platform.

The most urgent issue is a **confirmed LiveKit project credential disclosure** in the minimal worker generator. Network publication also lacks a safe, usable authentication mode, and core transfer/eligibility policy checks fail in targeted tests. Several compliance, health, privacy, and analytics displays claim stronger verification or data quality than the implementation provides.

| Area | Assessment |
|---|---|
| Controlled local demonstration | **Conditional use only**, with the policy and accuracy caveats below |
| LAN exposure using the supplied IIS path | **No-Go** |
| Production voice operations | **No-Go** |
| Secret management | **Fail** due to the minimal LiveKit bundle; current tracked files otherwise contained no live key |
| Conversation policy enforcement | **Fail** for disabled transfers and account-holder/eligibility handling |
| Functional completeness | **Partial**; many provider and agent settings are metadata rather than working behavior |
| Analytics/compliance reliability | **Low** due to random, zero, hard-coded, or misrepresented values |
| Automated test assurance | **Low to moderate** for basic flows, **low** for security and production readiness |
| Windows deployment portability | **Fail by source inspection**; machine-specific paths and watchdog wiring remain |
| Static frontend/assets | **Generally good**, with accessibility and content-claim issues |

### Finding totals

- **1 Critical**
- **8 High**
- **8 Medium**
- **2 Low**
- **19 consolidated findings**

Consolidation avoids counting the same root cause repeatedly. Additional concrete defects are listed under the relevant findings.

---

## 2. What was audited and how

### Methods used

- Read and traced the backend routes, database schema, seed/migration logic, deterministic engine, provider adapters, LiveKit builder/CLI integration, security controls, retention, analytics, and telephony mocks.
- Reviewed the main first-party frontend controllers, shared API/shell code, page markup, marketing/privacy content, and Windows launch/publish/watchdog scripts; checked every first-party JavaScript file syntactically and reviewed legacy security/configuration separately.
- Ran the application locally with no provider credentials and exercised normal and adversarial API paths.
- Ran a second instance with Bearer authentication enabled to verify the gate and its frontend implications.
- Ran Python compilation, JavaScript syntax checks, the documented offline smoke suite, targeted policy reproductions, generated-worker syntax checks, route/asset checks, Ruff, Bandit, and a focused npm audit.
- Scanned the current tracked tree for common credential patterns and reviewed vendored dependency identification.

### Execution results

| Check | Result | Interpretation |
|---|---:|---|
| Python compilation: `server.py`, `smoke_test.py`, `legacy/server.py` | **PASS** | Tested with Python 3.11.2; the README recommends 3.12 |
| `node --check` on 17 first-party JS files | **PASS** | Syntax only; not a browser behavior test |
| 17 application/legacy page routes | **PASS: all HTTP 200** | Included `/`, `/foundation`, `/admin`, `/deepgram`, `/livekit`, marketing, privacy, and `/legacy/` |
| Offline smoke suite, `--skip-live` | **FAIL: exit 1** | Actual results: **12 passed, 2 failed, 8 skipped** out of 22 checks |
| Smoke summary rendering | **FAIL** | Printed the impossible summary **`20/14 passed`** because skipped checks are counted as passes |
| Deterministic regression invoked by smoke suite | **9/9 reported pass** | Useful narrow check, but assertions are too shallow to establish production safety |
| Security self-test | **9/9 reported pass** | Several checks are hard-coded passes rather than executed security tests |
| Agent CRUD/version smoke flow | **PASS** | Create/read/update/version checks passed |
| Basic session loop | **PASS** | Session creation, turns, persistence, and deletion worked |
| Live-dial enable gate | **PASS** | Live telephony enablement was refused as intended; this does not validate transfer policy logic |
| Default generated starter/minimal Python | **PASS: both compile** | Adversarial names/model/dispatch values produced invalid Python |
| Brand PNG/SVG/manifest/font checks | **PASS** | PNG dimensions, SVG parsing, manifest JSON, and WOFF2 signatures validated |
| Ruff | **87 diagnostics** | Includes unused imports, broad exception handling, dead code, style, and maintainability findings; not all are defects |
| Bandit | **31 findings: 6 medium, 25 low, 0 high** | Manually triaged; automated scanning did **not** detect the critical credential leak |
| `npm audit` for `livekit-client@2.23.0` dependency tree | **0 reported vulnerabilities** | Narrow result only; not a whole-project SBOM or Tailwind/Python audit |
| Current tracked-tree credential scan | **No live credential identified** | Does not cover Git history or runtime-generated files |

### Important limitations

- No Deepgram or LiveKit credentials were present, and this environment does not permit access to those provider hosts. **Live provider synthesis, transcription, room control, deployment, SIP, egress, and cloud simulations were not exercised.**
- No graphical browser was available. JavaScript was syntax-checked and source-reviewed, but microphone capture, speech synthesis/recognition, responsive layout, focus behavior, and real browser playback were not interactively tested.
- Windows IIS, PowerShell, Task Scheduler, VBScript, self-signed certificate installation, and firewall behavior were **source-inspected only** on this Linux host.
- The checkout contains one grafted commit. Historical secret exposure and earlier implementation changes could not be audited.
- No load test was run. Concurrency concerns below are based on code structure and targeted API behavior, not a claimed stress-test reproduction.

---

## 3. Critical finding

### C-01 — Minimal LiveKit builds disclose the real project API key and secret

**Severity: Critical — confirmed by source and a sentinel reproduction**

`livekit_build_worker()` creates a file named `.env.example` containing the actual server values:

- `server.py:2589-2593`: `LIVEKIT_API_KEY={LIVEKIT_API_KEY}` and `LIVEKIT_API_SECRET={LIVEKIT_API_SECRET}`.
- `server.py:4682`: `/api/livekit/build` returns the generated files to the browser.
- `server.py:4757`: `/api/livekit/build.zip` packages the same generated content for download.

A test using non-secret sentinel values confirmed that both sentinel credentials appear in the minimal bundle. The starter template uses blank placeholders; the selectable **minimal/legacy** template is the affected path.

**Impact**

- Anyone who can reach the build or ZIP endpoint can recover the LiveKit **project API key and secret**.
- The secret can then reside in browser memory, downloaded ZIPs, screenshots, logs, or shared artifacts.
- The default unauthenticated LAN publication significantly increases the impact.
- This directly contradicts the UI and documentation claims that provider secrets never enter the browser.

**Required action**

1. Replace both values with blank placeholders in every generated `.env.example`.
2. Keep real deployment credentials exclusively in the server-side subprocess environment; never serialize them into a preview or archive.
3. Inspect both templates and every generated file for all provider credentials, not only LiveKit.
4. Add a regression test that injects unique dummy secrets and asserts their absence from JSON, every previewed file, and the unzipped archive.
5. **Rotate the LiveKit project key/secret if this minimal bundle has ever been generated with real credentials.** Review downloaded artifacts and provider access logs. Rotation is not necessary merely for this audit because no real key was used here.

---

## 4. High-severity findings

### H-01 — The supplied network deployment has no safe, usable authentication mode

**Severity: High — confirmed by source and authenticated runtime checks**

The direct Python server correctly binds to `127.0.0.1` (`server.py:5035`), but the IIS publishing path weakens that boundary:

- `.env.example:18` disables authentication by default.
- `publish-iis.ps1:258-263` first attempts a wildcard HTTP binding rather than limiting exposure to the selected LAN address.
- The firewall rule uses `Profile Any`.
- The publish script does not require or verify authentication before exposing the application.
- Administrative APIs include deletion, transcript access, room creation/deletion, join-token minting, worker build, simulation, and deployment.

When `AUTH_ENABLED=true` was tested, unauthenticated `/api/agents` correctly returned 401 and the same request with the Bearer token returned 200. However, the shipped browser application cannot use that mode: `assets/js/api.js` and the page-specific direct `fetch()` calls never attach `Authorization`. Static pages still load, but their API calls fail.

**Impact**

- With auth disabled, a network user receives the full control plane.
- With auth enabled, the normal UI is effectively unusable unless a separately designed reverse proxy injects authentication—which is not supplied as a complete secure solution.
- Opaque session UUIDs are identifiers, not user authorization boundaries.

**Required action**

- Keep the current IIS site private until a complete authentication solution exists.
- Terminate identity-aware authentication at a reverse proxy or implement secure server-side sessions; do not place a shared Bearer secret in JavaScript.
- Bind only intended interfaces, restrict firewall scope, and deny network publication by default.
- Add role/permission separation for read-only viewing, agent editing, deletion, token minting, and deployment.
- Verify every frontend request path in authenticated end-to-end tests.

### H-02 — Disabled-transfer policy is bypassed

**Severity: High — reproduced**

Two independent paths fail to enforce `transferPolicy.enabled=false`:

1. `mock_call()` only checks `requireConsent` and missing consent (`server.py:1737-1745`); it never blocks on `enabled=false`.
2. The `awaiting_consent` branch in `engine_step()` (`server.py:1011`) executes a transfer without rechecking whether transfers are still enabled.

A runtime reproduction created an agent with:

```json
{"transferPolicy": {"enabled": false, "requireConsent": false}}
```

A transfer request returned `ok: true` and emitted `mock_transfer_connected`. A direct engine test also showed that a consent response can complete a transfer after the policy has been disabled.

**Impact**

The platform's explicit transfer safety control is not authoritative. Real PSTN dialing is currently blocked, which limits immediate external impact, but this defect must be fixed before any real adapter is connected.

**Required action**

- Centralize one transfer-authorization function and call it at every transfer entry point.
- Require `enabled=true`, valid consent when configured, an active eligible session, and dialer availability confirmation.
- Represent a requested transfer as **pending**, not completed, until the dialer confirms it.
- Add positive, negative, policy-change, standalone-mock, and concurrent-update tests.

### H-03 — Eligibility and consent state transitions can produce unsafe decisions

**Severity: High — reproduced**

The documented account-holder → ZIP → prior-coverage sequence is not implemented as a validated state machine:

- There is no stored account-holder verification value or prior-coverage value.
- After asking about eligibility, the engine accepted **“no I am not the account holder, ZIP 12345”** as a ZIP response and continued.
- A following **“no”** to prior coverage produced **“you appear eligible for our standard plan.”**
- Declining transfer consent with **“no”** falls into the generic echo response while remaining in `awaiting_consent`; there is no explicit refusal transition.
- A transfer can be marked `completed` while the reply says availability is still awaiting confirmation.

Relevant logic is in `server.py:937-1109`, especially the coverage and eligibility branches at `1058-1073`.

**Impact**

The engine can make an unsupported eligibility statement to exactly the wrong caller and provides unreliable consent handling. Generic healthcare, financial, sales, and support presets increase the risk of treating demo rules as domain-safe behavior.

**Required action**

- Model explicit `unknown / yes / no` values for account-holder status and coverage.
- Never infer eligibility from missing or negative evidence; use an “unable to determine” outcome.
- Add an explicit consent-declined path and make terminal states consistent across engine, session row, and events.
- Separate domain-specific policy packs from generic agents and have qualified domain owners approve decision logic.

### H-04 — Agent Studio configuration does not reliably control runtime behavior

**Severity: High — confirmed by runtime and call-path inspection**

The product presents a configurable multi-provider voice-agent builder, but the local playground always calls the deterministic `engine_step()` for conversation replies.

Confirmed examples:

- A custom greeting was saved but ignored; session creation generated a different greeting (`server.py:3563-3564`).
- Custom system instructions were not used to shape that session's replies.
- `conversationRules` were echoed into a generic caller reply rather than acting as guarded internal instructions.
- `enabledTools`, `safetyRestrictions`, and most LLM configuration are stored/validated but do not drive local tool execution or generation.
- OpenAI, Anthropic, and Gemini adapters perform connection tests only; they do not generate playground responses, including when keys are present.
- Whisper, OpenAI TTS, and ElevenLabs do not have equivalent playground STT/TTS execution paths.
- Deepgram STT persists `interimResults` and `endpointing`, but the pre-recorded request does not apply them.
- The advertised Deepgram streaming/turn-based surfaces are not implemented by the buffered `/api/stt` endpoint.
- Agent Studio voice edits do not consistently update `ttsConfig.model`, causing configuration/compliance drift.
- Every agent receives claims such as “Self-Learning,” “Multimodality,” and “Massive Training Data” without corresponding runtime evidence.

**Impact**

Users can reasonably believe a tested/deployed agent will behave according to its prompt, greeting, model, tools, and provider selections when much of that configuration is cosmetic or only used by a separate generated LiveKit worker.

**Required action**

- Either implement each advertised execution path or explicitly label it as metadata/planned functionality.
- Use the configured greeting and prompt, bind sessions to an agent version, and prevent internal instructions from being echoed to callers.
- Remove unsupported capability claims and distinguish “configured,” “reachable,” “executed successfully,” and “deployed.”

### H-05 — LiveKit worker generation is unvalidated and has inconsistent defaults

**Severity: High — confirmed**

`livekit_builder_save()` (`server.py:3010`) accepts values without a schema. Template rendering then interpolates model, dispatch, keyterm, and name values directly into Python/TOML/YAML-like output.

Confirmed results:

- Default starter and minimal generated Python both compile.
- A numeric agent name, quoted/newline STT model, and quoted/newline dispatch name each produced invalid starter Python.
- A numeric `keyterms` value was accepted and persisted through the API.
- Defaults pair `ttsModel = fishaudio/s2.1-pro` with `ttsVoice = flux-brittany-en` (`server.py:2982-2983`). The UI binds Deepgram voice IDs without consistently changing the inference provider/model; the template's own comments show different Deepgram model/voice namespaces.

Unescaped generated source is more than a syntax issue: if an untrusted user can reach build-and-deploy, crafted values can alter the worker that is deployed and executed.

**Required action**

- Add strict server-side schemas, size/range/type checks, provider-specific model/voice mapping, safe identifier generation, and reserved-word handling.
- Serialize Python string literals safely rather than performing raw template replacement.
- Compile and validate every generated artifact before preview or deployment; add startup tests against the actual pinned LiveKit SDK.
- Use a lockfile for generated projects and test the default worker in a disposable environment.

### H-06 — Retention and privacy controls are not enforced, while UI copy overstates privacy

**Severity: High — confirmed by usage tracing**

Retention settings are readable and writable (`server.py:3877-3910`), but no startup job, scheduled job, request hook, or cleanup routine applies `auto_delete` or transcript retention days. The consent disclosure is similarly stored but not inserted into session behavior.

Privacy/copy inconsistencies include:

- `assets/js/page-playground.js:48` says **“Audio stays local.”**
- `assets/js/shell.js:201` says **“All audio stays on localhost.”**
- Deepgram and potentially browser speech recognition process audio outside the local machine.
- `marketing/privacy.html` says audio is retained for the configured period, although this application does not persist call audio at all.
- The privacy page is explicitly placeholder text and is not launch-ready.

**Impact**

Transcripts can remain indefinitely despite an operator enabling auto-delete, and users may rely on inaccurate audio-processing and retention statements.

**Required action**

- Implement transactional, observable retention enforcement and test expired/non-expired records.
- State clearly that audio is not stored locally by this build, but is transmitted to configured speech processors.
- Apply the consent disclosure where required and record the disclosed version with each session.
- Replace placeholder privacy/contact content with reviewed, accurate wording before launch.

### H-07 — Health, compliance, and “live verification” displays create false assurance

**Severity: High — reproduced and source-confirmed**

Examples:

- With no Deepgram key and `account.connected=false`, `/api/deepgram/compliance` still labels STT, TTS, and Voice Agent as **`live`** (`server.py:1543-1567`).
- “No fabricated provider metrics” and some secret/compliance checks are hard-coded passes (`server.py:1536-1539`) despite random voice metrics and the separate LiveKit secret leak.
- `deepgram_account()` initializes `connected=true` when a key exists; a failed account request does not reliably change that to false.
- Provider registry status can be based on key presence and can become stale when credentials are later removed.
- `assets/js/page-foundation.js:89` sets **“7/7 pass”** unconditionally after a health response, even with missing optional capabilities; its rendered checklist contains six items.
- `assets/js/page-docs.js` treats a health response as syntax verification, the presence of agents as CRUD verification, and can toast “Deepgram configured” without proving it.
- The admin quality chart hard-codes a security self-test value of nine (`assets/js/page-admin.js:221`).

**Impact**

Operators can make go-live decisions from indicators that do not represent actual provider reachability, successful capability execution, or security verification.

**Required action**

- Use distinct states: `unconfigured`, `configured`, `reachable`, `capability-verified`, `degraded`, `failed`, and `not-implemented`.
- Derive every pass/fail from a real check with a timestamp and evidence; never hard-code a passing compliance result.
- Rename “compliance” to “configuration checks” unless a defined control framework is actually evaluated.

### H-08 — Windows publishing and watchdog configuration is machine-specific and fragile

**Severity: High — source-confirmed; Windows execution not available**

- `publish-iis.ps1:24` and `watchdog-backend.ps1:13` default to `C:\Users\Wave\Downloads\AdrieneVoiceStudio` instead of the checkout directory.
- `watchdog-backend.vbs:8` hard-codes the same path.
- The scheduled task created by the publisher does not pass its selected `-ProjectRoot` to the watchdog.
- `publish-iis.ps1:237-240` rewrites **all** requests to Python, not only `/api/*` and intended page routes. This undermines the documented sanitized-static-publish boundary and exposes whatever the Python static handler permits.
- `-RegisterStartup` is not used to condition the scheduled-task registration; registration is attempted regardless.
- The script creates an HTTP firewall rule but no corresponding rule for the configured HTTPS port.
- Machine-wide trust of a self-signed root certificate and the insecure-origin browser flag need explicit operational warning and replacement for production.

**Required action**

- Resolve project paths from `$PSScriptRoot`, pass them consistently, and validate all destructive publish paths before elevation.
- Proxy only explicit application/API routes; serve the sanitized static directory directly.
- Make startup registration conditional and add the intended HTTPS firewall behavior.
- Add a clean-VM Windows deployment test instead of relying on machine-specific “16/16” documentation.

---

## 5. Medium-severity findings

### M-01 — Analytics and runtime data correctness is unreliable

**Severity: Medium — multiple confirmed defects**

- Voice sessions receive random backend STT latency (`server.py:3640`) instead of measured provider/browser latency.
- New assistant turns are stored with `latency_ms=0`, while analytics preferentially selects nonzero assistant latency. Real sessions can therefore be omitted when seeded nonzero samples exist.
- The cumulative average formula at `server.py:3719` under-weights the latest measurement; a first 1 ms exchange produced an average of 0.
- The admin operations chart applies one global p95 to every daily row (`assets/js/page-admin.js:148`), presenting it as a time series.
- The session inspector reads `lastSTT`/`lastTTS`, but the backend writes `lastStt`/`lastTtsFirstAudio`; those fields remain blank.
- The inspector reads turn `createdAt`, while the API serializes it as `ts`.
- One barge-in was counted twice because both the route and engine increment the counter.
- Analytics totals use all matching sessions, while intent/session views use only the newest 200 before date filtering; larger datasets become internally inconsistent.
- Provider history is attributed using the agent's **current** provider configuration, not the provider/version used at session time.

**Recommendation:** store measured stage timestamps and agent/version/provider snapshots per turn, correct field names and formulas, remove random production metrics, and test aggregates against a known fixture dataset.

### M-02 — Smoke and security automation overstates coverage and contains defects

**Severity: Medium — reproduced**

- `--skip-live` still fails health/provider checks that require Deepgram to be connected, so the documented fresh offline QA path exits 1.
- Skipped results are recorded with `ok=true` and counted by `Report.passed`, producing `20/14 passed` (`smoke_test.py:139-140,184`).
- `check_livekit()` has an unreachable duplicate return and can reference `agents` when Cloud API authorization is absent and the variable was never assigned (`smoke_test.py:453-558`).
- Security self-tests for safe errors, turn caps, rate limiting, and backend-only keys are hard-coded passes (`server.py:4312-4325`), not behavioral tests. No authorization check is performed despite the UI title.
- Regression `expectedOutcome` is not asserted, the hard transfer violation looks for an intent value the engine does not emit, and synthetic transcript latencies are random.
- Tests run against the real application database and leave regression runs, fixtures, and mock telephony logs behind.
- There is no unit-test suite, browser E2E suite, CI workflow, or clean-install matrix.

**Recommendation:** separate offline and credentialed suites, fix count arithmetic and unreachable code, use isolated temporary databases, replace hard-coded self-tests with HTTP-level assertions, and add policy/security/browser tests to CI.

### M-03 — Request validation and cross-site request protections are inconsistent

**Severity: Medium — reproduced**

A state-changing agent creation request with `Content-Type: text/plain` and a foreign `Origin` was accepted with **201**. The server does not enforce JSON content type or validate Origin/CSRF tokens. This enables cross-site write attempts in unauthenticated deployments, even though wildcard CORS is correctly absent and response reading remains restricted.

`GET /api/sessions?limit=-1` was also accepted; SQLite interprets a negative limit as unbounded, bypassing the intended 200-row cap. Other inconsistencies include unbounded STT endpointing and incomplete builder/config validation.

**Recommendation:** require expected media types, validate Origin and use CSRF protection for browser-authenticated writes, clamp pagination to `1..200`, centralize schemas, and add oversized/chunked/slow-client tests.

### M-04 — Concurrency and scalability safeguards are insufficient

**Severity: Medium — architectural risk, not stress-test claimed**

- `ThreadingHTTPServer` creates an unbounded thread-per-request model with no explicit socket/request timeout.
- Body draining can attempt to consume a declared unread body after a size-related failure; slow clients can hold threads.
- Agent updates read the current version and then increment it without optimistic-lock checks; concurrent writes can conflict or return a 500.
- Session turn sequence/state updates have no compare-and-swap protection.
- Admin/analytics paths perform broad in-memory scans and large per-session transcript loads.
- LiveKit simulation uses one fixed scenario filename and global mutable state, so concurrent simulations can overwrite/unlink each other's data.
- Cache and reload/watchdog paths have limited synchronization and error observability.

**Recommendation:** use a bounded production server, request timeouts, transaction/version predicates, unique sequence constraints, per-run temporary files/locks, pagination, and load/race tests.

### M-05 — Some third-party payloads bypass output allowlisting/redaction

**Severity: Medium — potential exposure requiring live-provider validation**

`livekit_cloud_sip()` and `livekit_cloud_media()` return provider dictionaries, and `livekit_console()` sends them to the browser without applying the project's `redact()` helper or an explicit field allowlist (`server.py:2791-2821,2879+`). Depending on provider responses, trunk credentials, signed URLs, stream keys, metadata, or other sensitive fields could be exposed. Deepgram project member data also increases the need for proper operator authorization.

No live provider account was available to prove a particular secret field is returned, so this is a **potential exposure**, not a confirmed credential leak like C-01.

**Recommendation:** return explicit minimal schemas, recursively redact sensitive keys and URL credentials, and add fixtures copied from sanitized real provider responses.

### M-06 — CSV exports permit spreadsheet formula injection

**Severity: Medium — source-confirmed**

`assets/js/page-testing.js` quotes CSV fields but does not neutralize cells beginning with `=`, `+`, `-`, or `@`. Test case names and other user-controlled values can therefore become formulas when an operator opens the export in spreadsheet software.

**Recommendation:** prefix dangerous cells according to the target spreadsheet format, add a safe export test, and consider offering JSON as the default for untrusted content.

### M-07 — Accessibility and responsive usability need a dedicated pass

**Severity: Medium — source inspection**

- The admin UI uses extensive 7.5–10 px text and small controls, creating readability and touch-target concerns.
- Static inspection found a label targeting a missing `cloud-tts-provider` ID and potentially unlabelled controls in Agent Studio, Voice Lab, Playground, and legacy pages.
- The modal navigation sheet declares `aria-modal` but has no complete focus trap, focus restoration, or Escape behavior.
- Browser-level contrast, zoom/reflow, keyboard, and screen-reader behavior was not tested.

Positive notes: focus-visible styling and reduced-motion CSS exist, and no duplicate HTML IDs were found in the basic parser audit.

**Recommendation:** test against WCAG 2.2 AA, raise base text/control sizes, repair labels, and add keyboard/focus E2E tests at mobile and desktop widths.

### M-08 — Documentation and public product content have material drift

**Severity: Medium — confirmed examples**

- README documents `POST /api/sessions/{id}/end`; the implementation uses `PATCH /api/sessions/{id}`.
- README documents `/api/security/retention`; the implementation uses `/api/retention`.
- Database table names in the README (`events`, `policies`) do not match the schema (`session_events`, `retention`).
- README says 12 per-agent checks; the current implementation constructs 11.
- The quoted “16/16” historical verification does not match the current runner, which produced 22 checks and a broken summary.
- `.env.example` omits `GEMINI_API_KEY`, although the backend and model catalogue use it.
- Marketing describes outbound qualification, VICIdial/CRM handoff, live transfer, and real-time transcript behavior beyond the current implementation. Placeholder markers are helpful, but the feature claims still need correction.
- The marketing privacy policy, contact details, structured-data URL, and sample proof content remain placeholders.

**Recommendation:** generate API documentation from the router, add documentation checks to CI, and maintain a clear implemented/partial/planned capability matrix.

---

## 6. Low-severity findings

### L-01 — Maintainability, dependency governance, and project controls need improvement

**Severity: Low immediate risk, rising maintenance risk**

- `server.py` is 5,092 lines and combines HTTP, persistence, policy, providers, code generation, deployment, security, and analytics.
- Ruff reported 87 diagnostics, including duplicate/unused imports, dead code, broad exception handling, and silent failures. These should be triaged rather than blindly auto-fixed.
- There is no CI configuration, test dependency manifest, application SBOM, contribution guide, license, or third-party notice file.
- The core has no LiveKit runtime dependency manifest despite optional imports; generated starter dependencies intentionally lack a lockfile.
- Vendored Tailwind's exact artifact version is not documented; LiveKit browser code identifies itself as 2.23.0.

**Recommendation:** split backend modules by responsibility, introduce versioned migrations and pinned dependency/SBOM automation, run Ruff/unit/smoke/browser checks in CI, and add appropriate license/third-party notices.

### L-02 — Static response hardening and attack surface can be tightened

**Severity: Low for the default loopback mode; higher if network-published**

Good baseline headers were observed: `nosniff`, `SAMEORIGIN`, `no-referrer`, and a microphone Permissions Policy. There is no Content Security Policy or HSTS on the direct server. The direct static handler can also serve documentation and operational scripts that are unnecessary for the UI, and `/legacy/` remains reachable with CDN dependencies and an outdated client-side-key architecture (its current key is blank).

**Recommendation:** use a static allowlist, remove legacy and operational files from the served root, add a tested CSP after reducing inline script/style dependence, add HSTS only at a proper HTTPS terminator, and avoid machine-wide self-signed trust for production.

---

## 7. Positive findings worth preserving

- The direct Python server is loopback-only by default, and real SIP/PSTN enablement is deliberately refused.
- `.env`, data, databases, logs, and caches are gitignored; the static handler blocks key private file types and path traversal.
- No live credential was found in the current tracked source scan; the legacy Deepgram key field is blank.
- SQL access is predominantly parameterized. Bandit's dynamic-SQL warnings were reviewed; no direct user-controlled SQL injection was confirmed.
- Frontend output generally uses `UI.esc()`/`UI.attr()` for dynamic HTML, and no straightforward stored XSS was confirmed in the reviewed main pages.
- All tested page routes rendered, all first-party JS parsed, and the basic agent/session workflows functioned offline.
- The project has no Node build requirement for its main UI and ships local fonts/assets; the smoke suite's 11-page no-CDN check passed, and the remaining current pages were source-reviewed.
- Brand assets are valid, consistently organized, and lightweight.
- Default generated workers are syntactically valid; problems arise from unvalidated values and deployment semantics rather than every default being malformed.
- The focused npm audit reported no known vulnerability for the `livekit-client@2.23.0` dependency tree at audit time. This should not be generalized to the entire project.

---

## 8. Prioritized remediation plan

### Immediate — before any further network exposure

1. **Fix C-01 and rotate affected LiveKit project credentials if the minimal generator has been used with real values.**
2. **Disable or firewall the IIS/LAN deployment** until authenticated UI and API access works end to end.
3. Bind publication to explicit interfaces and proxy only approved routes; remove legacy and operational files from the served surface.
4. Disable eligibility/transfer claims in demos until H-02/H-03 are fixed; real dialing must remain blocked.
5. Add secret-leak regression tests covering both generated templates, JSON responses, and ZIP contents.

### Next — core correctness and security

6. Implement one authoritative transfer/eligibility policy engine with explicit negative/unknown states and pending-versus-confirmed transfer statuses.
7. Add strict request/build schemas and safe code generation; correct model/voice mappings and compile/test every generated bundle.
8. Implement real retention enforcement and rewrite audio/privacy/consent disclosures to match actual data flows.
9. Replace hard-coded health/compliance/verification results with evidence-backed checks.
10. Remove random production latency, fix aggregate formulas/field names, and snapshot agent/provider versions on every session/turn.
11. Make Agent Studio behavior match its configuration or clearly reduce the advertised feature set.
12. Make Windows paths relative to the checkout and test publication/watchdogs on a clean Windows VM.

### Follow-up — assurance and maintainability

13. Repair the smoke reporter, isolate test data, replace hard-coded self-tests, and add unit, security, concurrency, browser, and generated-worker tests.
14. Add Origin/content-type/CSRF controls, strict pagination, spreadsheet-safe exports, and bounded request handling.
15. Split the backend into modules, add versioned migrations, SBOM/lockfiles, CI, accessibility checks, and generated API documentation.

---

## 9. Release acceptance checklist

Do not reconsider network or production release until all of these are demonstrated:

- [ ] A dummy LiveKit project key/secret appears in **no** API response, preview file, ZIP, log, or browser artifact for either template.
- [ ] Unauthenticated network callers cannot read transcripts, mutate data, mint room tokens, or deploy workers; the shipped UI works through the real auth flow.
- [ ] `transferPolicy.enabled=false` blocks every direct, consent, mock, and future real transfer path.
- [ ] A non-account-holder or negative/unknown coverage answer never produces an eligibility approval.
- [ ] Transfer state remains pending until an actual adapter confirms the outcome.
- [ ] Custom greeting/prompt/provider settings have documented, tested execution semantics.
- [ ] Enabling auto-delete removes expired transcripts and preserves unexpired data; audio/privacy copy matches actual processing and storage.
- [ ] Keyless compliance shows unconfigured/offline rather than live, and every pass has executable evidence.
- [ ] Analytics match a known fixture exactly, with no random production measurements or hard-coded daily/security values.
- [ ] A fresh offline checkout passes an accurately counted offline suite with exit code 0.
- [ ] Credentialed provider tests are separate, optional, reproducible, and do not contaminate the production database.
- [ ] Default and adversarial builder inputs either generate valid, startable workers or return a safe 400 response.
- [ ] The IIS publisher works from a clean checkout on a clean Windows VM without machine-specific paths and exposes only intended routes/interfaces.
- [ ] Browser microphone, playback, keyboard/focus, mobile layout, and authenticated end-to-end flows pass on supported browsers.

---

## 10. Reproduction commands used

```bash
# Static syntax
python3 -m py_compile server.py smoke_test.py legacy/server.py
for f in assets/js/*.js legacy/assets/js/*.js; do node --check "$f"; done

# Local application and documented offline suite
python3 server.py --port 8765 --no-open
python3 smoke_test.py --base-url http://127.0.0.1:8765 --skip-live

# Static analysis
python3 -m ruff check server.py smoke_test.py legacy/server.py
python3 -m bandit -r server.py legacy/server.py

# Focused dependency audit (temporary directory, not project metadata)
npm install --package-lock-only --ignore-scripts --no-audit livekit-client@2.23.0
npm audit
```

Additional short API scripts verified route responses, foreign-Origin/text-plain writes, negative pagination, custom greeting behavior, barge-in counts, disabled transfers, eligibility/consent paths, auth behavior, and generated source syntax. No real provider credentials or real phone numbers were used.

---

**Final assessment:** retain the local-first asset/UI foundation, but treat the current backend as prototype code. Fix the credential disclosure and network boundary immediately, then rebuild confidence through authoritative policy logic, truthful telemetry, enforced retention, and independent automated verification before any production use.

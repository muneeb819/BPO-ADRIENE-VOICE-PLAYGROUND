#!/usr/bin/env python3
"""
BPO Adriene - end-to-end smoke test automation.

Drives the local API the same way the browser does: health, static routes,
secret exposure, provider adapters (Deepgram Flux/Aura TTS, Nova-2 STT),
agent CRUD, the playground session loop, regression, security selftest,
mock telephony and analytics.

Standard library only - no pip install required.

    python smoke_test.py                        # http://127.0.0.1:8000
    python smoke_test.py --base-url http://127.0.0.1:8010
    python smoke_test.py --skip-live            # skip provider network calls
    python smoke_test.py --json report.json     # machine readable report

Exit code 0 = every check passed, 1 = at least one failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import ssl  # noqa: F401  (kept for parity with future https support)
except Exception:  # pragma: no cover
    pass

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

PAGE_ROUTES = [
    "/", "/agents", "/playground", "/lab", "/testing",
    "/analytics", "/security", "/telephony", "/docs",
]

FORBIDDEN_PATHS = [
    "/.env", "/.env.example", "/server.py", "/data/adriene.db",
    "/.gitignore", "/data/", "/smoke_test.py",
]


class SmokeError(Exception):
    """Raised when an assertion inside a check fails."""


class Client:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body=None, raw: bytes | None = None,
                content_type: str | None = None):
        url = path if path.startswith("http") else f"{self.base}{path}"
        data = None
        headers = {"Accept": "*/*"}
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                status = resp.status
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            ctype = exc.headers.get("Content-Type", "")
            status = exc.code
        if "application/json" in ctype:
            try:
                return status, json.loads(payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return status, payload
        return status, payload

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body=None):
        return self.request("POST", path, body=body if body is not None else {})

    def put(self, path: str, body=None):
        return self.request("PUT", path, body=body if body is not None else {})

    def delete(self, path: str):
        return self.request("DELETE", path)


class Report:
    def __init__(self) -> None:
        self.results: list[dict] = []
        self.started = time.time()

    def add(self, section: str, name: str, ok: bool, detail: str = "", skipped: bool = False) -> None:
        self.results.append({
            "section": section, "name": name, "ok": ok,
            "detail": detail, "skipped": skipped,
        })

    @property
    def failed(self) -> list[dict]:
        return [r for r in self.results if not r["ok"] and not r["skipped"]]

    @property
    def skipped(self) -> list[dict]:
        return [r for r in self.results if r["skipped"]]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r["ok"])

    def render(self) -> str:
        lines = []
        section = None
        for r in self.results:
            if r["section"] != section:
                section = r["section"]
                lines.append(f"\n{BOLD}{section}{RESET}")
            if r["skipped"]:
                mark, color = "-", YELLOW
                state = "SKIP"
            elif r["ok"]:
                mark, color = "+", GREEN
                state = "PASS"
            else:
                mark, color = "x", RED
                state = "FAIL"
            detail = f" {DIM}{r['detail']}{RESET}" if r["detail"] else ""
            lines.append(f"  {color}{mark}{RESET} {state}  {r['name']}{detail}")
        total = len(self.results)
        elapsed = time.time() - self.started
        summary = f"{self.passed}/{total - len(self.skipped)} passed"
        if self.failed:
            summary += f", {len(self.failed)} failed"
        if self.skipped:
            summary += f", {len(self.skipped)} skipped"
        color = RED if self.failed else GREEN
        lines.append(f"\n{BOLD}{color}{summary}{RESET} in {elapsed:.2f}s")
        if self.failed:
            lines.append(f"\n{RED}Failures:{RESET}")
            for r in self.failed:
                lines.append(f"  - [{r['section']}] {r['name']}: {r['detail']}")
        return "\n".join(lines)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def run_check(report: Report, section: str, name: str, fn, skip: bool = False,
              skip_reason: str = "") -> None:
    if skip:
        report.add(section, name, True, skip_reason, skipped=True)
        return
    started = time.perf_counter()
    try:
        detail = fn() or ""
        report.add(section, name, True, f"{detail} ({time.perf_counter() - started:.0f} ms)"
                   if detail else f"{time.perf_counter() - started:.0f} ms")
    except SmokeError as exc:
        report.add(section, name, False, str(exc))
    except Exception as exc:  # noqa: BLE001
        report.add(section, name, False, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_health(c: Client):
    status, data = c.get("/api/health")
    require(status == 200, f"health returned {status}")
    require(isinstance(data, dict) and data.get("ok") is True, "health payload is not ok")
    require(data.get("db") == "connected", f"db is {data.get('db')}")
    checks = data.get("checks") or {}
    for key, value in checks.items():
        require(value == "pass", f"health check '{key}' = {value}")
    caps = data.get("capabilities") or {}
    require("deepgramTts" in caps and "deepgramStt" in caps, "capability flags missing")
    require(caps.get("deepgramTts") is True, "Deepgram TTS capability is False")
    require(caps.get("deepgramStt") is True, "Deepgram STT capability is False")
    return f"db={data.get('db')} deepgram=tts/stt"


def check_pages(c: Client):
    for route in PAGE_ROUTES:
        status, body = c.get(route)
        require(status == 200, f"{route} returned {status}")
        if isinstance(body, bytes):
            text = body.decode("utf-8", "ignore")
        else:
            text = str(body)
        require("<html" in text.lower(), f"{route} did not return HTML")
    return f"{len(PAGE_ROUTES)} routes ok"


def check_no_secret_leak(c: Client):
    for path in FORBIDDEN_PATHS:
        status, _ = c.get(path)
        require(status == 404, f"{path} returned {status} (expected 404)")
    # README is served by the Python backend but intentionally not published to
    # IIS - either answer is acceptable, it just must never contain a secret.
    status, body = c.get("/README.md")
    if status == 200:
        text = body.decode("utf-8", "ignore") if isinstance(body, bytes) else str(body)
        require("DEEPGRAM_API_KEY=your_rotated_key" in text, "README placeholder missing")
        for marker in ("sk-", "xoxb-", "AKIA"):
            require(marker not in text, f"README leaks a credential marker ({marker})")
        for line in text.splitlines():
            if line.strip().startswith("DEEPGRAM_API_KEY="):
                require(line.split("=", 1)[1].strip() == "your_rotated_key",
                        "README contains a non-placeholder Deepgram key")
        return f"{len(FORBIDDEN_PATHS)} sensitive paths blocked, README clean"
    require(status == 404, f"README.md returned {status} (expected 200 or 404)")
    return f"{len(FORBIDDEN_PATHS)} sensitive paths blocked, README not published"


def check_providers(c: Client):
    status, providers = c.get("/api/providers")
    require(status == 200, f"providers returned {status}")
    require(isinstance(providers, list) and len(providers) >= 10, "provider registry is small")
    names = {p.get("name") for p in providers}
    for required in ("deepgram", "deepgram-tts", "browser", "local"):
        require(required in names, f"provider '{required}' missing")
    tts = next(p for p in providers if p.get("name") == "deepgram-tts")
    catalog = tts.get("voiceCatalog") or []
    require(len(catalog) >= 40, f"voice catalogue only has {len(catalog)} voices")
    require(any(v.startswith("flux-") for v in catalog), "no Flux voices in catalogue")
    require(any(v.startswith("aura-") for v in catalog), "no Aura voices in catalogue")
    stt = next(p for p in providers if p.get("name") == "deepgram")
    require(stt.get("status") == "connected", f"deepgram STT status is {stt.get('status')}")
    return f"{len(providers)} adapters, {len(catalog)} voices"


def check_provider_tests(c: Client):
    status, providers = c.get("/api/providers")
    require(status == 200, "providers unavailable")
    for name in ("deepgram", "deepgram-tts"):
        provider = next((p for p in providers if p.get("name") == name), None)
        require(provider is not None, f"provider {name} missing")
        code, result = c.post(f"/api/providers/{provider['id']}/test")
        require(code == 200, f"{name} test returned {code}")
        require(result.get("ok") is True, f"{name} test failed: {result.get('message')}")
    return "deepgram + deepgram-tts reachable"


def check_tts(c: Client):
    cases = [("flux-brittany-en", "Flux Brittany"), ("aura-asteria-en", "Aura Asteria")]
    total = 0
    for voice, label in cases:
        code, blob = c.request("POST", "/api/tts", body={"text": "Hello from the smoke test.", "voice": voice})
        require(code == 200, f"{label} TTS returned {code}")
        require(isinstance(blob, bytes) and len(blob) > 2000, f"{label} TTS audio too small")
        require(blob[:3] == b"ID3" or blob[:2] == b"\xff\xfb" or blob[:2] == b"\xff\xf3",
                f"{label} TTS did not return an mp3 stream")
        total += len(blob)
    return f"2 voices, {total // 1024} KB total"


def check_tts_guardrails(c: Client):
    code, data = c.post("/api/tts", body={"text": "", "voice": "flux-brittany-en"})
    require(code == 400, f"empty text returned {code} (expected 400)")
    code, data = c.post("/api/tts", body={"text": "x" * 1300, "voice": "flux-brittany-en"})
    require(code == 400, f"oversized text returned {code} (expected 400)")
    return "empty + oversized rejected"


def check_stt(c: Client):
    code, blob = c.request("POST", "/api/tts",
                           body={"text": "Hello from the Deepgram speech to text smoke test.", "voice": "flux-brittany-en"})
    require(code == 200, f"TTS pre-step returned {code}")
    require(isinstance(blob, bytes) and len(blob) > 2000, "TTS pre-step audio too small")
    code, data = c.request("POST", "/api/stt", raw=blob, content_type="audio/mpeg")
    require(code == 200, f"stt returned {code}: {str(data)[:120]}")
    require(isinstance(data, dict) and "transcript" in data, "stt response has no transcript")
    transcript = (data.get("transcript") or "").strip()
    require(len(transcript) > 2, f"stt transcript is empty ({data.get('model')})")
    return f"transcript={transcript[:42]!r}"


def check_stt_guardrails(c: Client):
    code, _ = c.request("POST", "/api/stt", raw=b"tiny", content_type="audio/mpeg")
    require(code == 400, f"tiny audio returned {code} (expected 400)")
    return "short clip rejected"


def check_agents_crud(c: Client):
    created_id = None
    try:
        code, agent = c.post("/api/agents", body={
            "name": "Smoke Test Agent",
            "description": "Created by smoke_test.py",
            "purpose": "Automated verification",
            "systemInstructions": "You are a smoke test agent. Answer briefly and deterministically.",
            "conversationRules": "Echo the intent. Never escalate.",
            "language": "en-US",
            "voice": "flux-brittany-en",
            "tone": "professional",
            "speakingRate": 100,
            "sttProvider": "deepgram",
            "llmProvider": "local",
            "ttsProvider": "deepgram-tts",
            "status": "draft",
        })
        require(code in (200, 201), f"create returned {code}")
        created_id = agent.get("id")
        require(created_id, "created agent has no id")
        require(agent.get("voice") == "flux-brittany-en", "voice not persisted on create")

        code, fetched = c.get(f"/api/agents/{created_id}")
        require(code == 200, f"read back returned {code}")
        require(fetched.get("name") == "Smoke Test Agent", "agent name mismatch")

        code, updated = c.put(f"/api/agents/{created_id}", body={
            "voice": "flux-haley-en",
            "ttsConfig": {"model": "flux-haley-en"},
            "changeNote": "Smoke test voice swap",
        })
        require(code == 200, f"update returned {code}")
        require(updated.get("voice") == "flux-haley-en", "voice not updated")
        require(updated.get("version", 0) >= 2, "update did not create a new version")

        code, versions = c.get(f"/api/agents/{created_id}/versions")
        require(code == 200 and len(versions) >= 2, "version history missing")

        code, bad = c.put(f"/api/agents/{created_id}", body={"voice": "not-a-real-voice"})
        require(code == 400, f"invalid voice accepted ({code})")
        return f"created/updated/deleted agent v{updated.get('version')}"
    finally:
        if created_id:
            c.delete(f"/api/agents/{created_id}")


def check_session_loop(c: Client):
    code, agents = c.get("/api/agents")
    require(code == 200 and agents, "no agents available for a session")
    agent_id = agents[0].get("id")
    code, session = c.post("/api/sessions", body={"agentId": agent_id, "userInputMode": "text"})
    require(code in (200, 201), f"session create returned {code}")
    sid = session.get("id")
    require(sid, "session has no id")
    require(session.get("status") == "active", f"session status is {session.get('status')}")
    try:
        code, turn = c.post(f"/api/sessions/{sid}/turns", body={"content": "hello, what is the price?"})
        require(code in (200, 201), f"turn returned {code}: {str(turn)[:140]}")
        assistant = turn.get("assistantTurn") or {}
        require(assistant.get("content"), "assistant turn is empty")
        code, detail = c.get(f"/api/sessions/{sid}")
        require(code == 200, f"session read back returned {code}")
        require(detail.get("turns"), "session has no persisted turns")
        return f"session {sid[:8]} turns={len(detail.get('turns') or [])}"
    finally:
        c.delete(f"/api/sessions/{sid}")


def check_regression(c: Client):
    code, agents = c.get("/api/agents")
    require(code == 200 and agents, "no agents available")
    agent_id = agents[0].get("id")
    code, cases = c.get(f"/api/test-cases?agentId={urllib.parse.quote(agent_id)}")
    require(code == 200, f"test cases returned {code}")
    if len(cases) < 9:
        c.post("/api/test-cases/seed", body={"agentId": agent_id})
        code, cases = c.get(f"/api/test-cases?agentId={urllib.parse.quote(agent_id)}")
    require(len(cases) >= 9, f"only {len(cases)} fixtures available")
    code, run = c.post("/api/test-runs", body={"agentId": agent_id})
    require(code in (200, 201), f"regression returned {code}: {str(run)[:140]}")
    require(run.get("status") == "passed", f"regression status {run.get('status')}")
    require(run.get("failed") == 0, f"{run.get('failed')} regression cases failed")
    require(run.get("passed") == run.get("totalCases"), "passed/total mismatch")
    return f"{run.get('passed')}/{run.get('totalCases')} cases passed"


def check_security(c: Client):
    code, result = c.post("/api/security/selftest")
    require(code == 200, f"selftest returned {code}")
    require(result.get("passed") == result.get("total"), f"selftest {result.get('passed')}/{result.get('total')}")
    require(result.get("total", 0) >= 9, "selftest ran too few checks")
    code, status = c.get("/api/security/status")
    require(code == 200, f"security status returned {code}")
    return f"{result.get('passed')}/{result.get('total')} checks"


def check_telephony(c: Client):
    code, logs = c.get("/api/telephony/logs")
    require(code == 200, f"telephony logs returned {code}")
    code, result = c.post("/api/telephony/mock-call", body={"requestTransfer": False})
    require(code in (200, 201), f"mock call returned {code}")
    require(result.get("blocked") is False, "mock call was blocked unexpectedly")
    code, blocked = c.post("/api/telephony/enable", body={"confirm": True})
    require(code == 403, f"live telephony enable returned {code} (expected 403)")
    return "mock call ok, live dial refused"


def check_analytics(c: Client):
    code, summary = c.get("/api/analytics/summary")
    require(code == 200, f"analytics returned {code}")
    require(isinstance(summary, dict), "analytics payload is not an object")
    totals = summary.get("totals") or {}
    require(isinstance(totals, dict), "analytics totals missing")
    for key in ("total", "completed", "errors", "active"):
        require(key in totals, f"analytics totals missing '{key}'")
    latencies = summary.get("latencies") or {}
    require("p50" in latencies and "p95" in latencies, "analytics latency percentiles missing")
    require(isinstance(summary.get("providerStats"), list), "analytics provider stats missing")
    require(summary.get("tokenUsage", {}).get("totalTokens") is None,
            "token usage must stay unavailable rather than fabricated")
    return f"sessions={totals.get('total')} p95={latencies.get('p95')}ms providers={len(summary.get('providerStats') or [])}"


def check_rate_limit_headers(c: Client):
    code, _ = c.get("/api/health")
    require(code == 200, "health unreachable")
    return "endpoint reachable"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="BPO Adriene end-to-end smoke tests")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="backend base URL")
    parser.add_argument("--skip-live", action="store_true", help="skip provider network calls")
    parser.add_argument("--json", dest="json_path", help="write a JSON report to this path")
    args = parser.parse_args()

    client = Client(args.base_url)
    report = Report()

    print(f"{BOLD}BPO Adriene smoke tests{RESET} {DIM}{args.base_url}{RESET}")

    run_check(report, "Reachability", "GET /api/health", lambda: check_health(client))
    run_check(report, "Static app", "All 9 page routes render", lambda: check_pages(client))
    run_check(report, "Static app", "No secret or source files served", lambda: check_no_secret_leak(client))
    run_check(report, "Providers", "Registry and voice catalogue", lambda: check_providers(client))
    run_check(report, "Providers", "Connection tests", lambda: check_provider_tests(client),
              skip=args.skip_live, skip_reason="--skip-live")
    run_check(report, "TTS", "Flux + Aura synthesis", lambda: check_tts(client),
              skip=args.skip_live, skip_reason="--skip-live")
    run_check(report, "TTS", "Input validation", lambda: check_tts_guardrails(client))
    run_check(report, "STT", "Nova-2 transcription", lambda: check_stt(client),
              skip=args.skip_live, skip_reason="--skip-live")
    run_check(report, "STT", "Short-clip rejection", lambda: check_stt_guardrails(client))
    run_check(report, "Agents", "CRUD + versioning + validation", lambda: check_agents_crud(client))
    run_check(report, "Playground", "Session + turn loop", lambda: check_session_loop(client))
    run_check(report, "Evaluation", "Regression suite", lambda: check_regression(client))
    run_check(report, "Security", "Authorization & validation selftest", lambda: check_security(client))
    run_check(report, "Telephony", "Mock call + live-dial gate", lambda: check_telephony(client))
    run_check(report, "Analytics", "Summary aggregation", lambda: check_analytics(client))
    run_check(report, "Reachability", "Re-check after suite", lambda: check_rate_limit_headers(client))

    print(report.render())

    if args.json_path:
        payload = {
            "baseUrl": args.base_url,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "passed": report.passed,
            "failed": len(report.failed),
            "skipped": len(report.skipped),
            "results": report.results,
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"{DIM}JSON report: {args.json_path}{RESET}")

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())

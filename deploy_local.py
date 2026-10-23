#!/usr/bin/env python3
"""
Local deployment helper for BPO Adriene / Tressa.

Runs the unified server on 0.0.0.0:8010 so it's accessible via:
  - http://localhost:8010
  - http://127.0.0.1:8010
  - http://192.168.18.29:8010  (your LAN IP)
  - http://<your-lan-ip>:8010

For HTTPS on LAN (https://192.168.18.29), use a reverse proxy like:
  - Caddy: `caddy reverse-proxy --from 192.168.18.29:443 --to localhost:8010`
  - nginx with self-signed cert
  - mkcert + Python's http.server SSL wrapper

Usage:
    python deploy_local.py                    # HTTP on 0.0.0.0:8010
    python deploy_local.py --port 8010        # Custom port
    python deploy_local.py --no-open          # Don't open browser
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER_PY = ROOT / "server.py"


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "192.168.18.29"


def main():
    parser = argparse.ArgumentParser(description="Deploy BPO Adriene locally on LAN")
    parser.add_argument("--port", type=int, default=8010, help="HTTP port (default 8010)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    parser.add_argument("--lan-ip", default=None, help="LAN IP (auto-detected if omitted)")
    args = parser.parse_args()

    lan_ip = args.lan_ip or get_lan_ip()
    print(f"\n  BPO ADRIENE / TRESSA -- Local LAN Deployment")
    print(f"  Detected LAN IP: {lan_ip}")
    print(f"  Binding to       : 0.0.0.0:{args.port}")
    print()
    print(f"  Accessible at:")
    print(f"    http://localhost:{args.port}")
    print(f"    http://127.0.0.1:{args.port}")
    print(f"    http://{lan_ip}:{args.port}")
    print()
    print(f"  Pages:")
    print(f"    Admin Panel      -> http://{lan_ip}:{args.port}/")
    print(f"    Tressa Dashboard -> http://{lan_ip}:{args.port}/tressa")
    print(f"    Agent Studio     -> http://{lan_ip}:{args.port}/agents")
    print(f"    Voice Playground -> http://{lan_ip}:{args.port}/playground")
    print(f"    LiveKit Console  -> http://{lan_ip}:{args.port}/livekit")
    print(f"    API Health       -> http://{lan_ip}:{args.port}/api/health")
    print(f"    Training API     -> http://{lan_ip}:{args.port}/api/training")
    print()
    print(f"  For HTTPS on LAN (https://{lan_ip}:443), run a reverse proxy:")
    print(f"    # Option A: Caddy (simplest, auto TLS)")
    print(f"    caddy reverse-proxy --from {lan_ip}:443 --to localhost:{args.port}")
    print(f"    # Option B: mkcert + nginx/Caddy")
    print(f"    mkcert -install && mkcert {lan_ip} localhost 127.0.0.1")
    print(f"    # Then configure nginx/Caddy with the cert")
    print()
    print(f"  Stop: Ctrl+C\n")

    env = os.environ.copy()
    env["BIND_HOST"] = "0.0.0.0"
    env["PORT"] = str(args.port)
    if args.no_open:
        env["ADRIENE_NO_OPEN"] = "1"

    print(f"  Starting server on 0.0.0.0:{args.port}...")
    try:
        proc = subprocess.Popen([sys.executable, str(SERVER_PY), "--port", str(args.port)],
                                env=env)
    except Exception as e:
        print(f"  Failed to start: {e}")
        return 1

    def shutdown(signum, frame):
        print("\n  Shutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        proc.wait()
    except KeyboardInterrupt:
        shutdown(None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
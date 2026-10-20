#!/usr/bin/env python3
"""Local development server for Adriene Voice Studio.

Serves the project over http://localhost so the microphone API is available
(browsers block getUserMedia on file:// pages).

    python server.py            # serve on port 8000 and open the browser
    python server.py --port 9000 --no-open
"""

import argparse
import http.server
import os
import socketserver
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        print("  " + fmt % args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="Serve Adriene Voice Studio locally.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-open", action="store_true", help="do not open a browser tab")
    args = parser.parse_args()

    httpd = None
    port = args.port
    last_error = None
    for candidate in range(args.port, args.port + 10):
        try:
            httpd = Server(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as exc:
            last_error = exc

    if httpd is None:
        print(f"\n  Cannot listen on ports {args.port}-{args.port + 9}: {last_error}")
        print("  Try a specific port:  python server.py --port 9000\n")
        return 1

    if port != args.port:
        print(f"\n  Port {args.port} is busy, using {port} instead.")

    url = f"http://localhost:{port}/"
    print("\n  Adriene Voice Studio")
    print("  " + "-" * 42)
    print(f"  Folder : {ROOT}")
    print(f"  URL    : {url}")
    print("  Stop   : Ctrl+C\n")

    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    finally:
        httpd.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Dedicated EC2 analysis agent on :8080.

Starts with MediaMTX. On publisher ready, buffers 5 minutes of RTMP (via local
RTSP), uploads to S3 under tmp/lives/<path-id>/, notifies the API which runs
FFmpeg frames + ASR + Luna and bills -5 minutes per analyzed window.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("STREAMCLIP_AGENT_PORT", "8080"))
STATE_DIR = Path(os.environ.get("STREAMCLIP_STATE_DIR", "/var/run/streamclip"))
LOG = Path(os.environ.get("STREAMCLIP_AGENT_LOG", "/var/log/streamclip-agent.log"))

_lock = threading.Lock()
_loops: dict[str, subprocess.Popen] = {}
_started_at = time.time()


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n"
    try:
        with LOG.open("a") as fh:
            fh.write(line)
    except OSError:
        pass


def _load_env() -> None:
    env_path = Path("/etc/streamclip/agent.env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        if "=" not in raw or raw.startswith("#"):
            continue
        key, _, val = raw.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def start_path(path: str) -> dict:
    path = path.strip().lstrip("/")
    if not path:
        return {"ok": False, "error": "path required"}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        proc = _loops.get(path)
        if proc is not None and proc.poll() is None:
            return {"ok": True, "path": path, "status": "already_running", "pid": proc.pid}
        env = os.environ.copy()
        log_fh = open("/var/log/streamclip-segment.log", "a")
        proc = subprocess.Popen(
            ["/usr/local/bin/streamclip-segment-loop", path],
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _loops[path] = proc
        _log(f"start path={path} pid={proc.pid}")
        return {"ok": True, "path": path, "status": "started", "pid": proc.pid}


def stop_path(path: str) -> dict:
    path = path.strip().lstrip("/")
    with _lock:
        proc = _loops.pop(path, None)
    safe = path.replace("/", "_").replace(":", "_")
    pidfile = STATE_DIR / f"seg_{safe}.pid"
    killed: list[int] = []
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            killed.append(proc.pid)
        except OSError:
            try:
                proc.terminate()
                killed.append(proc.pid)
            except OSError:
                pass
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
            pidfile.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    _log(f"stop path={path} killed={killed}")
    return {"ok": True, "path": path, "killed": killed}


def status() -> dict:
    with _lock:
        paths = {}
        for path, proc in list(_loops.items()):
            paths[path] = {
                "pid": proc.pid,
                "running": proc.poll() is None,
                "exit_code": proc.poll(),
            }
    return {
        "ok": True,
        "role": "dedicated-analysis",
        "port": PORT,
        "uptime_s": int(time.time() - _started_at),
        "rtmp_port": 1935,
        "paths": paths,
        "s3_bucket": os.environ.get("S3_BUCKET") or None,
        "event_url": bool(os.environ.get("EVENT_URL")),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        _log("%s - " % self.address_string() + (fmt % args))

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/health", "/"):
            self._json(200, {"ok": True, "role": "dedicated-analysis", "port": PORT})
            return
        if parsed.path == "/status":
            self._json(200, status())
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            body = {}
        qs = parse_qs(parsed.query)
        path = body.get("path") or (qs.get("path") or [None])[0] or ""
        if parsed.path == "/start":
            self._json(200, start_path(str(path)))
            return
        if parsed.path == "/stop":
            self._json(200, stop_path(str(path)))
            return
        self._json(404, {"ok": False, "error": "not_found"})


def main() -> None:
    _load_env()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    _log(f"listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

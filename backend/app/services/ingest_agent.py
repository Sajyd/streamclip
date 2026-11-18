#!/usr/bin/env python3
"""Dedicated EC2 analysis agent on :8080.

Public GET /health and /status (JSON or HTML). POST /start|/stop localhost-only.
GET /hls/… proxies local MediaMTX HLS (127.0.0.1:8888) for dashboard preview —
gated by the ingest hook secret or a short-lived API preview token (no OBS secret).
Never exposes stream secrets or full remote control to the internet.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("STREAMCLIP_AGENT_PORT", "8080"))
HLS_UPSTREAM = os.environ.get("STREAMCLIP_HLS_UPSTREAM", "http://127.0.0.1:8888")
STATE_DIR = Path(os.environ.get("STREAMCLIP_STATE_DIR", "/var/run/streamclip"))
SEGMENTS_DIR = Path(os.environ.get("STREAMCLIP_SEGMENTS_DIR", "/var/lib/streamclip/segments"))
LOG = Path(os.environ.get("STREAMCLIP_AGENT_LOG", "/var/log/streamclip-agent.log"))
MAX_BODY = 4096
RATE_LIMIT_PER_MIN = 120
_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,198}$")
_SAFE_HLS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,240}$")

_lock = threading.Lock()
# Supervised 5-min RTMP segment loops (exact wall-clock cadence).
_loops: dict[str, subprocess.Popen] = {}
_started_at = time.time()
_rate: dict[str, deque[float]] = defaultdict(deque)
_net_prev: tuple[float, int, int] | None = None  # ts, rx, tx
_net_bps: tuple[float, float] = (0.0, 0.0)


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


def _sanitize_path(path: str) -> str | None:
    path = (path or "").strip().lstrip("/")
    if not path or ".." in path or path.startswith(".") or not _SAFE_PATH.match(path):
        return None
    return path


def _public_path_label(path: str) -> str:
    """Hide stream-key material; show live/<public_id> only."""
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "live":
        pid = parts[1]
        if len(pid) > 12:
            pid = pid[:8] + "…"
        return f"live/{pid}"
    if len(path) > 40:
        return path[:20] + "…" + path[-8:]
    return path


def _is_loopback(client: str) -> bool:
    return client in ("127.0.0.1", "::1", "localhost")


def _allow_request(client: str) -> bool:
    now = time.time()
    q = _rate[client]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return False
    q.append(now)
    return True


def _read_mem() -> dict:
    out = {"total_mb": None, "available_mb": None, "used_pct": None}
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            num = v.strip().split()[0]
            info[k] = int(num)
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        if total > 0:
            out["total_mb"] = round(total / 1024)
            out["available_mb"] = round(avail / 1024)
            out["used_pct"] = round(100 * (1 - avail / total), 1)
    except OSError:
        pass
    return out


def _read_load() -> list[float] | None:
    try:
        raw = Path("/proc/loadavg").read_text().split()
        return [float(raw[0]), float(raw[1]), float(raw[2])]
    except (OSError, ValueError, IndexError):
        return None


def _read_disk(path: Path) -> dict:
    out = {"path": str(path), "total_gb": None, "used_gb": None, "free_gb": None, "used_pct": None}
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        out["total_gb"] = round(total / (1024**3), 2)
        out["used_gb"] = round(used / (1024**3), 2)
        out["free_gb"] = round(free / (1024**3), 2)
        out["used_pct"] = round(100 * used / total, 1) if total else None
    except OSError:
        pass
    return out


def _read_net() -> dict:
    """Approx RX/TX bitrates on the primary non-lo interface."""
    global _net_prev, _net_bps
    rx = tx = 0
    iface = None
    try:
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if name == "lo":
                continue
            cols = rest.split()
            r, t = int(cols[0]), int(cols[8])
            if r + t >= rx + tx:
                rx, tx, iface = r, t, name
    except (OSError, ValueError, IndexError):
        return {"iface": None, "rx_mbps": 0.0, "tx_mbps": 0.0}
    now = time.time()
    if _net_prev is not None:
        dt = max(0.001, now - _net_prev[0])
        _net_bps = (
            max(0.0, (rx - _net_prev[1]) * 8 / dt / 1_000_000),
            max(0.0, (tx - _net_prev[2]) * 8 / dt / 1_000_000),
        )
    _net_prev = (now, rx, tx)
    return {
        "iface": iface,
        "rx_mbps": round(_net_bps[0], 2),
        "tx_mbps": round(_net_bps[1], 2),
    }


def _buffer_stats() -> dict:
    active = 0
    sequences: list[dict] = []
    pending_bytes = 0
    with _lock:
        for path, proc in list(_loops.items()):
            running = proc.poll() is None
            if running:
                active += 1
            safe = path.replace("/", "_").replace(":", "_")
            seq = 0
            seqfile = STATE_DIR / f"seg_{safe}.seq"
            if seqfile.exists():
                try:
                    seq = int(seqfile.read_text().strip() or "0")
                except ValueError:
                    seq = 0
            sequences.append(
                {
                    "path": _public_path_label(path),
                    "running": running,
                    "next_sequence": seq,
                    "buffer_window_s": 300,
                    "recorder": "ffmpeg-rtmp",
                }
            )
    try:
        if SEGMENTS_DIR.is_dir():
            for f in SEGMENTS_DIR.iterdir():
                if f.is_file() and f.suffix == ".mp4":
                    pending_bytes += f.stat().st_size
    except OSError:
        pass
    return {
        "active_buffers": active,
        "window_s": 300,
        "pending_segment_bytes": pending_bytes,
        "pending_segment_mb": round(pending_bytes / (1024 * 1024), 2),
        "streams": sequences,
    }


def _path_state_file(clean: str) -> Path:
    safe = clean.replace("/", "_").replace(":", "_")
    return STATE_DIR / f"seg_{safe}.path"


def _remember_path(clean: str) -> None:
    """Persist MTX path so an agent restart can re-attach the segment loop."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path_state_file(clean).write_text(clean + "\n")
    except OSError as exc:
        _log(f"remember_path_failed path={_public_path_label(clean)} err={exc}")


def _paths_from_state() -> list[str]:
    found: list[str] = []
    if not STATE_DIR.is_dir():
        return found
    try:
        files = sorted(STATE_DIR.glob("seg_*.path"))
    except OSError:
        return found
    for file in files:
        try:
            raw = file.read_text().strip()
        except OSError:
            continue
        clean = _sanitize_path(raw)
        if clean and clean not in found:
            found.append(clean)
    return found


def _orphan_loop_pid(clean: str) -> int | None:
    """PID of an unmanaged streamclip-segment-loop still holding this path."""
    safe = clean.replace("/", "_").replace(":", "_")
    pidfile = STATE_DIR / f"seg_{safe}.pid"
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return None
    if "streamclip-segment-loop" not in cmdline:
        return None
    if clean not in cmdline:
        return None
    return pid


def _spawn_loop(clean: str) -> subprocess.Popen:
    env = os.environ.copy()
    log_fh = open("/var/log/streamclip-segment.log", "a")  # noqa: SIM115 — kept for child lifetime
    return subprocess.Popen(
        ["/usr/local/bin/streamclip-segment-loop", clean],
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def start_path(path: str) -> dict:
    clean = _sanitize_path(path)
    if clean is None:
        return {"ok": False, "error": "invalid_path"}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _remember_path(clean)
    with _lock:
        proc = _loops.get(clean)
        if proc is not None and proc.poll() is None:
            return {
                "ok": True,
                "path": _public_path_label(clean),
                "status": "already_running",
                "recorder": "ffmpeg-rtmp",
            }
        # Orphan from a previous agent process: take ownership with a fresh supervised loop.
        orphan = _orphan_loop_pid(clean)
        if orphan is not None:
            try:
                os.kill(orphan, signal.SIGTERM)
            except OSError:
                pass
            time.sleep(0.25)
        proc = _spawn_loop(clean)
        _loops[clean] = proc
        _log(f"start path={_public_path_label(clean)} pid={proc.pid} recorder=ffmpeg-rtmp")
        return {
            "ok": True,
            "path": _public_path_label(clean),
            "status": "started",
            "recorder": "ffmpeg-rtmp",
        }


def recover_loops() -> int:
    """Re-start segment loops for every remembered live path (agent reboot safe)."""
    started = 0
    for path in _paths_from_state():
        result = start_path(path)
        if result.get("status") == "started":
            started += 1
    if started:
        _log(f"recover_loops started={started}")
    return started


def _respawn_dead_loops() -> int:
    """If a segment loop exited, restart it — never tear down the live."""
    restarted = 0
    with _lock:
        known = set(_loops)
        for path, proc in list(_loops.items()):
            if proc.poll() is None:
                continue
            fresh = _spawn_loop(path)
            _loops[path] = fresh
            restarted += 1
            _log(
                f"respawn path={_public_path_label(path)} "
                f"old_exit={proc.returncode} new_pid={fresh.pid}"
            )
    # Paths remembered on disk but missing from memory (post-agent-restart).
    for path in _paths_from_state():
        if path in known:
            continue
        if start_path(path).get("status") == "started":
            restarted += 1
    return restarted


def stop_path(path: str) -> dict:
    clean = _sanitize_path(path)
    if clean is None:
        return {"ok": False, "error": "invalid_path"}
    with _lock:
        proc = _loops.pop(clean, None)
    safe = clean.replace("/", "_").replace(":", "_")
    pidfile = STATE_DIR / f"seg_{safe}.pid"
    killed = 0
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            killed += 1
        except OSError:
            try:
                proc.terminate()
                killed += 1
            except OSError:
                pass
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            killed += 1
            pidfile.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    _log(f"stop path={_public_path_label(clean)} killed={killed}")
    return {"ok": True, "path": _public_path_label(clean), "killed": killed}


def health() -> dict:
    restarted = _respawn_dead_loops()
    with _lock:
        active = sum(1 for proc in _loops.values() if proc.poll() is None)
    return {
        "ok": True,
        "role": "dedicated-analysis",
        "port": PORT,
        "uptime_s": int(time.time() - _started_at),
        "rtmp_port": 1935,
        "active_buffers": active,
        "respawned": restarted,
        "recorder": "ffmpeg-rtmp",
        "storage_configured": bool(os.environ.get("S3_BUCKET")),
        "ffmpeg": bool(shutil.which("ffmpeg") or Path("/usr/local/bin/ffmpeg").is_file()),
    }


def status() -> dict:
    buf = _buffer_stats()
    return {
        "ok": True,
        "role": "dedicated-analysis",
        "port": PORT,
        "uptime_s": int(time.time() - _started_at),
        "uptime_human": _fmt_uptime(int(time.time() - _started_at)),
        "rtmp_port": 1935,
        "storage_configured": bool(os.environ.get("S3_BUCKET")),
        "event_hook_configured": bool(os.environ.get("EVENT_URL")),
        "memory": _read_mem(),
        "loadavg": _read_load(),
        "disk_root": _read_disk(Path("/")),
        "disk_segments": _read_disk(SEGMENTS_DIR if SEGMENTS_DIR.exists() else Path("/var/lib")),
        "bandwidth": _read_net(),
        "buffer": buf,
    }


def _fmt_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _hook_secret() -> str:
    return (os.environ.get("HOOK") or os.environ.get("INGEST_HOOK_SECRET") or "").strip()


def _authorized_preview(handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
    """Allow HLS proxy with hook secret header/query or API-minted preview token.

    Never requires the user's clear OBS stream secret.
    """
    expected = _hook_secret()
    if not expected:
        return True
    header = (handler.headers.get("X-Streamclip-Ingest-Secret") or "").strip()
    if header and hmac.compare_digest(header, expected):
        return True
    provided = (query.get("ingest_secret") or query.get("secret") or [None])[0]
    if provided and hmac.compare_digest(str(provided), expected):
        return True
    token = (query.get("token") or [None])[0]
    if not token or not str(token).startswith("pb."):
        return False
    parts = str(token).split(".")
    if len(parts) != 4:
        return False
    _, public_id, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    payload = f"{public_id}:{exp}".encode()
    expected_sig = hmac.new(expected.encode(), payload, hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected_sig)


def _proxy_hls(handler: BaseHTTPRequestHandler, subpath: str) -> None:
    if not subpath or ".." in subpath or not _SAFE_HLS.match(subpath):
        handler._json(404, {"ok": False, "error": "not_found"})
        return
    upstream = f"{HLS_UPSTREAM.rstrip('/')}/{subpath.lstrip('/')}"
    try:
        with urllib.request.urlopen(upstream, timeout=8) as resp:  # noqa: S310
            data = resp.read()
            content_type = resp.headers.get("Content-Type") or "application/octet-stream"
            handler.send_response(200)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler._security_headers()
            handler.end_headers()
            handler.wfile.write(data)
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        handler.send_response(exc.code)
        handler.send_header("Content-Type", exc.headers.get("Content-Type", "text/plain"))
        handler.send_header("Content-Length", str(len(body)))
        handler._security_headers()
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as exc:  # noqa: BLE001
        _log(f"hls proxy error path={subpath} err={exc}")
        handler._json(502, {"ok": False, "error": "hls_unavailable"})


def _wants_html(handler: BaseHTTPRequestHandler) -> bool:
    qs = parse_qs(urlparse(handler.path).query)
    fmt = ((qs.get("format") or [None])[0] or "").lower()
    if fmt == "json":
        return False
    if fmt == "html":
        return True
    accept = (handler.headers.get("Accept") or "").lower()
    if "text/html" in accept:
        return True
    if "application/json" in accept:
        return False
    ua = (handler.headers.get("User-Agent") or "").lower()
    return any(tok in ua for tok in ("mozilla", "chrome", "safari", "edg/"))


def _render_html(title: str, payload: dict, *, page: str) -> bytes:
    data = html.escape(json.dumps(payload, indent=2))
    uptime = html.escape(str(payload.get("uptime_human") or payload.get("uptime_s", "—")))
    mem = payload.get("memory") or {}
    disk = payload.get("disk_segments") or payload.get("disk_root") or {}
    bw = payload.get("bandwidth") or {}
    buf = payload.get("buffer") or {}
    load = payload.get("loadavg") or []
    ok = bool(payload.get("ok"))
    streams = buf.get("streams") or []
    stream_rows = ""
    for s in streams:
        stream_rows += (
            f"<tr><td>{html.escape(str(s.get('path')))}</td>"
            f"<td>{'●' if s.get('running') else '○'}</td>"
            f"<td>{html.escape(str(s.get('next_sequence')))}</td>"
            f"<td>{html.escape(str(s.get('buffer_window_s')))}s</td></tr>"
        )
    if not stream_rows:
        stream_rows = '<tr><td colspan="4" class="muted">Aucun buffer actif</td></tr>'

    # Self-contained UI — no external assets (CSP-friendly).
    body = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="robots" content="noindex,nofollow"/>
<title>Streamclip · {html.escape(title)}</title>
<style>
:root {{
  --bg:#0b1220; --card:#121a2b; --ink:#e8eefc; --muted:#8b9bb8;
  --ok:#34d399; --bad:#f87171; --line:#243049; --accent:#5b8cff;
}}
* {{ box-sizing:border-box }}
body {{
  margin:0; min-height:100vh; font:15px/1.45 ui-sans-serif,system-ui,sans-serif;
  color:var(--ink); background:
    radial-gradient(900px 400px at 10% -10%, #1a2a4a 0%, transparent 55%),
    radial-gradient(700px 300px at 100% 0%, #132038 0%, transparent 50%),
    var(--bg);
}}
main {{ max-width:920px; margin:0 auto; padding:2rem 1.25rem 3rem }}
header {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.75rem 1.25rem; margin-bottom:1.5rem }}
h1 {{ margin:0; font-size:1.35rem; letter-spacing:-.02em }}
.badge {{
  display:inline-flex; align-items:center; gap:.4rem; padding:.2rem .65rem;
  border-radius:999px; font-size:.75rem; border:1px solid var(--line);
  background:var(--card);
}}
.badge.ok {{ color:var(--ok); border-color:#1f4d3a }}
.badge.bad {{ color:var(--bad); border-color:#5c2a2a }}
.nav a {{ color:var(--accent); text-decoration:none; margin-right:1rem; font-size:.9rem }}
.nav a:hover {{ text-decoration:underline }}
.grid {{ display:grid; gap:1rem; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin:1.25rem 0 }}
.card {{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:1rem 1.1rem;
}}
.card h2 {{ margin:0 0 .35rem; font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); font-weight:600 }}
.card .val {{ font-size:1.45rem; font-weight:650; letter-spacing:-.03em }}
.card .sub {{ margin-top:.25rem; font-size:.8rem; color:var(--muted) }}
.bar {{ height:6px; border-radius:99px; background:#1c263b; margin-top:.65rem; overflow:hidden }}
.bar > i {{ display:block; height:100%; background:linear-gradient(90deg,#3b82f6,#22d3ee); border-radius:99px }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem }}
th,td {{ text-align:left; padding:.55rem .4rem; border-bottom:1px solid var(--line) }}
th {{ color:var(--muted); font-weight:550; font-size:.72rem; text-transform:uppercase }}
.muted {{ color:var(--muted) }}
details {{ margin-top:1.25rem }}
pre {{
  margin:0; padding:1rem; overflow:auto; max-height:280px; font-size:.72rem;
  background:#0a101c; border:1px solid var(--line); border-radius:10px; color:#a8b8d8;
}}
footer {{ margin-top:1.5rem; font-size:.75rem; color:var(--muted) }}
</style>
{"<meta http-equiv='refresh' content='5'/>" if page == "status" else ""}
</head>
<body>
<main>
<header>
  <h1>Streamclip analysis</h1>
  <span class="badge {"ok" if ok else "bad"}">{"● healthy" if ok else "● degraded"}</span>
  <nav class="nav">
    <a href="/health">/health</a>
    <a href="/status">/status</a>
    <a href="/status?format=json">JSON</a>
  </nav>
</header>
<section class="grid">
  <article class="card"><h2>Uptime</h2><div class="val">{uptime}</div><div class="sub">agent :{PORT}</div></article>
  <article class="card"><h2>Buffers</h2><div class="val">{html.escape(str(buf.get("active_buffers", "—") if page=="status" else "—"))}</div><div class="sub">fenêtre {html.escape(str(buf.get("window_s", 300)))}s</div></article>
  <article class="card"><h2>Bandwidth</h2><div class="val">{html.escape(str(bw.get("rx_mbps", "—")))}<span style="font-size:.85rem;color:var(--muted)"> ↓</span></div><div class="sub">{html.escape(str(bw.get("tx_mbps", "—")))} Mbps ↑ · {html.escape(str(bw.get("iface") or "n/a"))}</div></article>
  <article class="card"><h2>Storage</h2><div class="val">{html.escape(str(disk.get("used_pct") if disk.get("used_pct") is not None else "—"))}%</div><div class="sub">{html.escape(str(disk.get("used_gb") or "—"))} / {html.escape(str(disk.get("total_gb") or "—"))} Go · S3 {"oui" if payload.get("storage_configured") else ("—" if page=="health" else "non")}</div><div class="bar"><i style="width:{min(100, float(disk.get("used_pct") or 0))}%"></i></div></article>
  <article class="card"><h2>Mémoire</h2><div class="val">{html.escape(str(mem.get("used_pct") if mem.get("used_pct") is not None else "—"))}%</div><div class="sub">{html.escape(str(mem.get("available_mb") or "—"))} Mo libres</div><div class="bar"><i style="width:{min(100, float(mem.get("used_pct") or 0))}%"></i></div></article>
  <article class="card"><h2>Load</h2><div class="val">{html.escape(" / ".join(str(x) for x in load) if load else "—")}</div><div class="sub">loadavg 1 / 5 / 15</div></article>
</section>
<section class="card">
  <h2>Buffers actifs</h2>
  <table>
    <thead><tr><th>Path</th><th>Run</th><th>Seq</th><th>Window</th></tr></thead>
    <tbody>{stream_rows}</tbody>
  </table>
  <p class="muted" style="margin:.75rem 0 0;font-size:.8rem">Pending local: {html.escape(str(buf.get("pending_segment_mb", 0)))} Mo</p>
</section>
<details>
  <summary class="muted">Payload brut</summary>
  <pre>{data}</pre>
</details>
<footer>Lecture seule · control API localhost-only · auto-refresh {("5s" if page=="status" else "off")}</footer>
</main>
</body>
</html>"""
    return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "StreamclipAgent/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        _log("%s - " % self.address_string() + (fmt % args))

    def _client_ip(self) -> str:
        # Ignore spoofable X-Forwarded-For — agent is edge-facing without a trusted proxy.
        return self.client_address[0]

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
            "script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, title: str, payload: dict, *, page: str) -> None:
        body = _render_html(title, payload, page=page)
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _rate_or_reject(self) -> bool:
        ip = self._client_ip()
        if not _allow_request(ip):
            self._json(429, {"ok": False, "error": "rate_limited"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._rate_or_reject():
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        want_html = _wants_html(self)
        if path in ("/health", "/"):
            payload = health()
            if want_html:
                # Light metrics on health page too for the dashboard cards.
                full = status()
                full.update(payload)
                self._html(200, "health", full, page="health")
            else:
                self._json(200, payload)
            return
        if path == "/status":
            payload = status()
            if want_html:
                self._html(200, "status", payload, page="status")
            else:
                self._json(200, payload)
            return
        if path.startswith("/hls/"):
            qs = parse_qs(parsed.query)
            if not _authorized_preview(self, qs):
                self._json(401, {"ok": False, "error": "unauthorized"})
                return
            _proxy_hls(self, path[len("/hls/") :])
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._rate_or_reject():
            return
        # Hard lock: mutation only from the box (MediaMTX runOn* hooks).
        if not _is_loopback(self._client_ip()):
            self._json(403, {"ok": False, "error": "localhost_only"})
            return
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            self._json(413, {"ok": False, "error": "body_too_large"})
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        qs = parse_qs(parsed.query)
        path = body.get("path") or (qs.get("path") or [None])[0] or ""
        route = parsed.path.rstrip("/")
        if route == "/start":
            self._json(200, start_path(str(path)))
            return
        if route == "/stop":
            self._json(200, stop_path(str(path)))
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_PUT(self) -> None:  # noqa: N802
        self._json(405, {"ok": False, "error": "method_not_allowed"})

    def do_DELETE(self) -> None:  # noqa: N802
        self._json(405, {"ok": False, "error": "method_not_allowed"})


def main() -> None:
    _load_env()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    recovered = recover_loops()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    _log(f"listening on :{PORT} recovered_loops={recovered}")
    server.serve_forever()


if __name__ == "__main__":
    main()

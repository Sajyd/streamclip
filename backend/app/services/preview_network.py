"""Keep live preview reachable: SG :8080 + on-box HLS proxy.

Dashboard HLS is proxied by the API to either the shared edge host or a
dedicated spot on :8080. Spots sometimes launch with a SG that lacks 8080, or
an agent/MediaMTX without local HLS. The API role repairs that in place.
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

_AGENT_PORT = 8080
_LOCK = threading.Lock()
_LAST_REPAIR_AT = 0.0
_REPAIR_COOLDOWN_SEC = 90.0

# Minimal edge HLS front (hook secret / preview token). Deployed via SSM when
# the shared ingest node still has `hls: no`.
_EDGE_HLS_PROXY = r'''#!/usr/bin/env python3
"""STREAMCLIP edge HLS preview proxy (:8080 → MediaMTX 127.0.0.1:8888)."""
from __future__ import annotations
import hashlib, hmac, os, re, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("STREAMCLIP_HLS_PORT", "8080"))
UPSTREAM = os.environ.get("STREAMCLIP_HLS_UPSTREAM", "http://127.0.0.1:8888")
SAFE = re.compile(r"^[A-Za-z0-9._/\-]+$")
HOOK = (os.environ.get("HOOK") or os.environ.get("INGEST_HOOK_SECRET") or "").strip()

def _ok(handler, q):
    if not HOOK:
        return True
    h = (handler.headers.get("X-Streamclip-Ingest-Secret") or "").strip()
    if h and hmac.compare_digest(h, HOOK):
        return True
    for k in ("ingest_secret", "secret"):
        v = (q.get(k) or [None])[0]
        if v and hmac.compare_digest(str(v), HOOK):
            return True
    tok = (q.get("token") or [None])[0]
    if not tok or not str(tok).startswith("pb."):
        return False
    parts = str(tok).split(".")
    if len(parts) != 4:
        return False
    _, pid, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    expect = hmac.new(HOOK.encode(), f"{pid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expect)

class H(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/health", "/"):
            body = b'{"ok":true,"service":"edge-hls"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not u.path.startswith("/hls/"):
            self.send_response(404); self.end_headers(); return
        if not _ok(self, q):
            self.send_response(401); self.end_headers(); return
        sub = u.path[len("/hls/"):]
        if not sub or ".." in sub or not SAFE.match(sub):
            self.send_response(404); self.end_headers(); return
        try:
            with urllib.request.urlopen(f"{UPSTREAM.rstrip('/')}/{sub}", timeout=8) as r:
                data = r.read()
                ct = r.headers.get("Content-Type") or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp else b""
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(502); self.end_headers()

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
'''


def edge_preview_host(settings: Settings) -> str | None:
    """Stable OBS edge hostname/IP used for dashboard HLS."""
    host = (settings.ingest_public_host or "").strip()
    if host:
        if "://" in host:
            parsed = urlparse(host)
            return parsed.hostname
        return host.split("/")[0].split(":")[0] or None
    explicit = (settings.ingest_rtmps_url or "").strip()
    if explicit:
        parsed = urlparse(explicit if "://" in explicit else f"rtmp://{explicit}")
        return parsed.hostname
    return None


def _ec2(settings: Settings):
    from app.aws.session import boto3_session

    return boto3_session(settings).client(
        "ec2",
        region_name=settings.ingest_ec2_region or settings.s3_region or "eu-north-1",
    )


def _ssm(settings: Settings):
    from app.aws.session import boto3_session

    return boto3_session(settings).client(
        "ssm",
        region_name=settings.ingest_ec2_region or settings.s3_region or "eu-north-1",
    )


def ensure_agent_ingress(settings: Settings, *, group_id: str | None = None) -> dict[str, Any]:
    """Ensure TCP 8080/0.0.0.0/0 on the dedicated (or given) security group."""
    sg = (group_id or settings.ingest_ec2_security_group_id or "").strip()
    if not sg:
        return {"ok": False, "error": "no_security_group"}
    ec2 = _ec2(settings)
    desc = ec2.describe_security_groups(GroupIds=[sg])
    groups = desc.get("SecurityGroups") or []
    if not groups:
        return {"ok": False, "error": "sg_not_found", "group_id": sg}
    perms = groups[0].get("IpPermissions") or []
    for perm in perms:
        if perm.get("IpProtocol") != "tcp":
            continue
        if int(perm.get("FromPort") or -1) > _AGENT_PORT:
            continue
        if int(perm.get("ToPort") or -1) < _AGENT_PORT:
            continue
        for rng in perm.get("IpRanges") or []:
            if rng.get("CidrIp") == "0.0.0.0/0":
                return {"ok": True, "group_id": sg, "changed": False}
    try:
        ec2.authorize_security_group_ingress(
            GroupId=sg,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": _AGENT_PORT,
                    "ToPort": _AGENT_PORT,
                    "IpRanges": [
                        {
                            "CidrIp": "0.0.0.0/0",
                            "Description": "STREAMCLIP live preview HLS proxy",
                        }
                    ],
                }
            ],
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "InvalidPermission.Duplicate" in msg:
            return {"ok": True, "group_id": sg, "changed": False}
        log.warning("preview.sg_authorize_failed", group_id=sg, error=msg)
        return {"ok": False, "group_id": sg, "error": msg}
    log.info("preview.sg_authorized", group_id=sg, port=_AGENT_PORT)
    return {"ok": True, "group_id": sg, "changed": True}


def _find_edge_instance(settings: Settings) -> dict[str, Any] | None:
    ec2 = _ec2(settings)
    host = edge_preview_host(settings)
    filters = [
        {"Name": "instance-state-name", "Values": ["running"]},
        {
            "Name": "tag:Name",
            "Values": [
                "streamclip-production-ingest",
                "streamclip-staging-ingest",
                "streamclip-preview-ingest",
            ],
        },
    ]
    resp = ec2.describe_instances(Filters=filters)
    candidates: list[dict[str, Any]] = []
    for res in resp.get("Reservations") or []:
        for inst in res.get("Instances") or []:
            candidates.append(inst)
    if not candidates and host:
        # Match by public IP / DNS when the Name tag filter is too strict.
        resp = ec2.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
        for res in resp.get("Reservations") or []:
            for inst in res.get("Instances") or []:
                pub = inst.get("PublicIpAddress") or ""
                dns = inst.get("PublicDnsName") or ""
                if host in (pub, dns) or host == pub:
                    candidates.append(inst)
    if not candidates:
        return None
    inst = candidates[0]
    sgs = [g.get("GroupId") for g in (inst.get("SecurityGroups") or []) if g.get("GroupId")]
    return {
        "instance_id": inst.get("InstanceId"),
        "public_ip": inst.get("PublicIpAddress"),
        "security_group_ids": sgs,
    }


def _ssm_run(settings: Settings, *, instance_id: str, commands: list[str]) -> dict[str, Any]:
    ssm = _ssm(settings)
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=120,
    )
    command_id = (resp.get("Command") or {}).get("CommandId")
    return {"ok": True, "command_id": command_id, "instance_id": instance_id}


def enable_edge_hls_proxy(settings: Settings, *, instance_id: str) -> dict[str, Any]:
    """SSM: turn on MediaMTX HLS + systemd proxy on :8080 for the edge node.

    Never restart MediaMTX unless the HLS block actually changed — a restart
    drops every OBS publisher on the shared edge and aborts 5-min segments.
    """
    proxy_b64 = base64.b64encode(_EDGE_HLS_PROXY.encode()).decode("ascii")
    # Never send the ingest hook through SSM — reuse the secret already on the box.
    script = f"""
set -euo pipefail
mkdir -p /usr/local/bin /etc/streamclip
echo '{proxy_b64}' | base64 -d > /usr/local/bin/streamclip-edge-hls.py
chmod +x /usr/local/bin/streamclip-edge-hls.py
python3 - <<'PY'
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
dest = Path("/etc/streamclip/edge-hls.env")
if dest.exists() and "HOOK=" in dest.read_text():
    os.chmod(dest, 0o600)
else:
    hook = ""
    cfg = Path("/etc/mediamtx/mediamtx.yml")
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.startswith("authHTTPAddress:"):
                url = line.split(":", 1)[1].strip()
                hook = (parse_qs(urlparse(url).query).get("ingest_secret") or [""])[0]
                break
    if hook:
        dest.write_text("HOOK=" + hook + "\\n")
        os.chmod(dest, 0o600)
PY
MTX_RESTART=0
if [ -f /etc/mediamtx/mediamtx.yml ]; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/etc/mediamtx/mediamtx.yml")
text = p.read_text()
lines = text.splitlines()
out = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.startswith("hls:"):
        out.append("hls: yes")
        i += 1
        # skip old hls* keys we rewrite
        while i < len(lines) and lines[i].startswith("hls") and not lines[i].startswith("hls:"):
            i += 1
        out.extend([
            "hlsAddress: 127.0.0.1:8888",
            "hlsAlwaysRemux: yes",
            "hlsSegmentCount: 7",
            "hlsSegmentDuration: 1s",
        ])
        continue
    out.append(line)
    i += 1
if not any(l.startswith("hls:") for l in out):
    # insert before rtsp or at end of top-level
    inserted = False
    final = []
    for l in out:
        if l.startswith("rtsp:") and not inserted:
            final.extend([
                "hls: yes",
                "hlsAddress: 127.0.0.1:8888",
                "hlsAlwaysRemux: yes",
                "hlsSegmentCount: 7",
                "hlsSegmentDuration: 1s",
            ])
            inserted = True
        final.append(l)
    out = final
new = "\\n".join(out) + "\\n"
if new != text:
    p.write_text(new)
    Path("/tmp/streamclip-mtx-hls-changed").write_text("1")
    print("mediamtx_hls_changed")
else:
    print("mediamtx_hls_unchanged")
PY
  if [ -f /tmp/streamclip-mtx-hls-changed ]; then
    rm -f /tmp/streamclip-mtx-hls-changed
    MTX_RESTART=1
  fi
  if [ "$MTX_RESTART" = "1" ]; then
    systemctl restart mediamtx || true
  fi
fi
cat > /etc/systemd/system/streamclip-edge-hls.service <<'UNIT'
[Unit]
Description=STREAMCLIP edge HLS preview (:8080)
After=network-online.target mediamtx.service
Wants=network-online.target
[Service]
Type=simple
EnvironmentFile=-/etc/streamclip/edge-hls.env
ExecStart=/usr/bin/python3 /usr/local/bin/streamclip-edge-hls.py
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now streamclip-edge-hls
# Restart only the HLS proxy (safe) — never bounce MediaMTX unless config changed.
systemctl restart streamclip-edge-hls
sleep 1
curl -fsS http://127.0.0.1:8080/health || true
ss -lntp | grep -E '8080|8888|1935' || true
"""
    try:
        return _ssm_run(settings, instance_id=instance_id, commands=[script])
    except Exception as exc:  # noqa: BLE001
        log.warning("preview.edge_ssm_failed", instance_id=instance_id, error=str(exc))
        return {"ok": False, "error": str(exc), "instance_id": instance_id}


def patch_dedicated_preview(
    settings: Settings, *, instance_id: str
) -> dict[str, Any]:
    """SSM: refresh dedicated agent + ensure MediaMTX local HLS.

    Skip MediaMTX rewrite/restart when HLS is already enabled — bouncing it
    kills the local RTMP publisher (edge relay) and the segment loop.
    """
    agent_path = Path(__file__).with_name("ingest_agent.py")
    agent_b64 = base64.b64encode(agent_path.read_bytes()).decode("ascii")
    script = f"""
set -euo pipefail
mkdir -p /usr/local/bin /etc/streamclip /var/run/streamclip
echo '{agent_b64}' | base64 -d > /tmp/streamclip-analysis-agent.new
AGENT_RESTART=0
if ! cmp -s /tmp/streamclip-analysis-agent.new /usr/local/bin/streamclip-analysis-agent.py 2>/dev/null; then
  install -m 755 /tmp/streamclip-analysis-agent.new /usr/local/bin/streamclip-analysis-agent.py
  AGENT_RESTART=1
  echo "dedicated_agent_updated"
else
  echo "dedicated_agent_unchanged"
fi
rm -f /tmp/streamclip-analysis-agent.new
if [ -f /etc/mediamtx/mediamtx.yml ]; then
  if grep -qE '^hls:[[:space:]]*yes' /etc/mediamtx/mediamtx.yml \\
    && grep -qE '^hlsAddress:[[:space:]]*127\\.0\\.0\\.1:8888' /etc/mediamtx/mediamtx.yml; then
    echo "dedicated_hls_already_ok"
  else
    AUTH_LINE=$(grep -E '^authHTTPAddress:' /etc/mediamtx/mediamtx.yml | head -1 || true)
    [ -n "${{AUTH_LINE:-}}" ] || AUTH_LINE='authHTTPAddress: http://127.0.0.1/'
    python3 -c 'import pathlib,sys; auth=sys.argv[1]; pathlib.Path("/etc/mediamtx/mediamtx.yml").write_text("logLevel: info\\nwriteQueueSize: 8192\\nreadTimeout: 60s\\nwriteTimeout: 60s\\nrtmp: yes\\nrtmpAddress: :1935\\nsrt: yes\\nsrtAddress: :8890\\nwebrtc: no\\nhls: yes\\nhlsAddress: 127.0.0.1:8888\\nhlsAlwaysRemux: yes\\nhlsSegmentCount: 7\\nhlsSegmentDuration: 1s\\nrtsp: yes\\nrtspAddress: :8554\\nauthMethod: http\\n"+auth+"\\npathDefaults:\\n  record: no\\n  runOnReady: /usr/local/bin/streamclip-on-ready $MTX_PATH\\n  runOnNotReady: /usr/local/bin/streamclip-on-not-ready $MTX_PATH\\npaths:\\n  all_others:\\n")' "$AUTH_LINE"
    systemctl restart mediamtx || true
  fi
fi
systemctl daemon-reload || true
systemctl enable --now streamclip-agent || true
# Only bounce the agent when its binary changed — a blind restart drops in-memory
# loop supervision. After any restart, re-/start every remembered live path.
if [ "$AGENT_RESTART" = "1" ] || ! systemctl is-active --quiet streamclip-agent; then
  systemctl restart streamclip-agent || true
  sleep 1
fi
for f in /var/run/streamclip/seg_*.path; do
  [ -f "$f" ] || continue
  PATH_NAME=$(tr -d '[:space:]' < "$f" || true)
  [ -n "$PATH_NAME" ] || continue
  curl -fsS -X POST -H 'Content-Type: application/json' \\
    -d "{{\\"path\\":\\"$PATH_NAME\\"}}" \\
    http://127.0.0.1:8080/start || true
done
curl -fsS http://127.0.0.1:8080/health || true
ss -lntp | grep -E '1935|8080|8888' || true
"""
    try:
        return _ssm_run(settings, instance_id=instance_id, commands=[script])
    except Exception as exc:  # noqa: BLE001
        log.warning("preview.dedicated_ssm_failed", instance_id=instance_id, error=str(exc))
        return {"ok": False, "error": str(exc), "instance_id": instance_id}


def repair_preview_network(
    settings: Settings,
    *,
    dedicated_instance_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Open :8080 and (re)install HLS proxies on edge + dedicated."""
    global _LAST_REPAIR_AT
    now = time.time()
    with _LOCK:
        if not force and now - _LAST_REPAIR_AT < _REPAIR_COOLDOWN_SEC:
            return {
                "ok": True,
                "skipped": True,
                "cooldown_sec": _REPAIR_COOLDOWN_SEC,
            }
        _LAST_REPAIR_AT = now

    result: dict[str, Any] = {"ok": True, "steps": []}
    try:
        sg = ensure_agent_ingress(settings)
        result["steps"].append({"ensure_sg": sg})
    except Exception as exc:  # noqa: BLE001
        result["steps"].append({"ensure_sg": {"ok": False, "error": str(exc)}})
        result["ok"] = False

    try:
        edge = _find_edge_instance(settings)
        result["edge"] = {
            "instance_id": edge.get("instance_id") if edge else None,
            "public_ip": edge.get("public_ip") if edge else None,
        }
        if edge and edge.get("security_group_ids"):
            for gid in edge["security_group_ids"]:
                result["steps"].append(
                    {"edge_sg": ensure_agent_ingress(settings, group_id=gid)}
                )
        if edge and edge.get("instance_id"):
            result["steps"].append(
                {
                    "edge_hls": enable_edge_hls_proxy(
                        settings, instance_id=edge["instance_id"]
                    )
                }
            )
    except Exception as exc:  # noqa: BLE001
        result["steps"].append({"edge": {"ok": False, "error": str(exc)}})
        result["ok"] = False

    if dedicated_instance_id:
        try:
            result["steps"].append(
                {
                    "dedicated": patch_dedicated_preview(
                        settings, instance_id=dedicated_instance_id
                    )
                }
            )
        except Exception as exc:  # noqa: BLE001
            result["steps"].append({"dedicated": {"ok": False, "error": str(exc)}})
            result["ok"] = False

    log.info("preview.repair_done", result=result)
    return result


def schedule_repair(
    settings: Settings, *, dedicated_instance_id: str | None = None
) -> None:
    """Fire-and-forget repair (safe to call from request handlers)."""

    def _run() -> None:
        try:
            repair_preview_network(
                settings, dedicated_instance_id=dedicated_instance_id, force=False
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("preview.repair_thread_failed", error=str(exc))

    threading.Thread(target=_run, name="preview-repair", daemon=True).start()

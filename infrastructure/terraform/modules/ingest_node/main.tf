# Single MediaMTX ingest node on the default VPC (MVP).
# Publishes RTMP 1935 + SRT UDP 8890. Auth is delegated to the STREAMCLIP API.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  dynamic "filter" {
    for_each = var.availability_zone == "" ? [] : [var.availability_zone]
    content {
      name   = "availability-zone"
      values = [filter.value]
    }
  }
}

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "ingest" {
  name        = "${var.name}-sg"
  description = "STREAMCLIP MediaMTX ingest"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "RTMP / RTMPS"
    from_port   = 1935
    to_port     = 1935
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SRT"
    from_port   = 8890
    to_port     = 8890
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Dedicated analysis agent"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = length(var.ssh_cidr_blocks) > 0 ? [1] : []
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_cidr_blocks
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name}-sg" }
}

resource "aws_iam_role" "ingest" {
  name = "${var.name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ingest_tmp" {
  name = "${var.name}-tmp"
  role = aws_iam_role.ingest.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectTagging",
          "s3:GetObject",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
          "s3:ListMultipartUploadParts",
        ]
        Resource = ["${var.bucket_arn}/tmp/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [var.bucket_arn]
        Condition = {
          StringLike = { "s3:prefix" = ["tmp/*", "tmp/lives/*"] }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:Converse",
          "transcribe:StartTranscriptionJob",
          "transcribe:GetTranscriptionJob",
          "transcribe:DeleteTranscriptionJob",
        ]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ingest.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ingest" {
  name = "${var.name}-profile"
  role = aws_iam_role.ingest.name
}

locals {
  event_url = var.api_event_url != "" ? var.api_event_url : replace(var.api_auth_url, "/auth", "/event")
  relay_url = replace(local.event_url, "/hooks/event", "/hooks/relay-target")
  userdata = <<-EOF
    #!/bin/bash
    # Shared edge: one RTMP URL for all OBS clients → ffmpeg relay to dedicated spot.
    set -eo pipefail
    mkdir -p /etc/mediamtx /var/run/streamclip /usr/local/bin
    if ! command -v ffmpeg >/dev/null 2>&1; then
      FFDIR=$(mktemp -d)
      curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz" -o "$FFDIR/ffmpeg.tar.xz"
      tar -xJf "$FFDIR/ffmpeg.tar.xz" -C "$FFDIR"
      install -m 755 "$FFDIR"/ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/ffmpeg
      install -m 755 "$FFDIR"/ffmpeg-*-arm64-static/ffprobe /usr/local/bin/ffprobe || true
      rm -rf "$FFDIR"
    fi
    AUTH_URL='${var.api_auth_url}'
    EVENT_URL='${local.event_url}'
    RELAY_URL='${local.relay_url}'
    HOOK='${var.ingest_hook_secret}'
    MTX_VER=1.12.3
    curl -fsSL "https://github.com/bluenviron/mediamtx/releases/download/v$${MTX_VER}/mediamtx_v$${MTX_VER}_linux_arm64.tar.gz" \
      | tar -xz -C /usr/local/bin mediamtx
    chmod +x /usr/local/bin/mediamtx

    cat > /usr/local/bin/streamclip-edge-relay <<'RELAY'
    #!/bin/bash
    # Poll until the per-org spot is ready (cold boot + MediaMTX userdata).
    # runOnNotReady kills this process when OBS disconnects — no hard timeout.
    PATH_NAME="$1"
    SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
    mkdir -p /var/run/streamclip
    PIDFILE="/var/run/streamclip/relay_$${SAFE}.pid"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      exit 0
    fi
    echo $$ > "$PIDFILE"
    trap 'rm -f "$PIDFILE"' EXIT
    while true; do
    TARGET=""
    ATTEMPT=0
    while true; do
      ATTEMPT=$((ATTEMPT + 1))
      RESP=$(curl -fsS -G -H "X-Streamclip-Ingest-Secret: $HOOK" \
        --data-urlencode "path=$PATH_NAME" "$RELAY_URL" || true)
      TARGET=$(printf '%s' "$RESP" | sed -n 's/.*"rtmp_push_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      STATUS=$(printf '%s' "$RESP" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      if [ "$STATUS" = "ready" ] && [ -n "$TARGET" ]; then
        break
      fi
      # Quota can return when the user subscribes without restarting OBS.
      # Keep polling; runOnNotReady kills this process if the publisher leaves.
      if [ "$STATUS" = "unavailable" ] && echo "$RESP" | grep -qiE 'quota|abonnement|subscription|refus'; then
        echo "relay waiting quota path=$PATH_NAME" >&2
        sleep 15
        continue
      fi
      if [ $((ATTEMPT % 20)) -eq 0 ]; then
        echo "relay waiting spot path=$PATH_NAME attempt=$ATTEMPT status=$STATUS" >&2
      fi
      sleep 3
    done
    curl -fsS -X POST -H Content-Type:application/json \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
      "$EVENT_URL" || true
    # Local remux via RTSP — MediaMTX RTMP readers die on OBS DTS jumps.
    # If the push to the spot stalls or drops while OBS is still publishing
    # here, kill ffmpeg and open a new push. Do not wait for OBS to reconnect.
    PROGRESS="/var/run/streamclip/relay_$${SAFE}.progress"
    rm -f "$PROGRESS"
    ffmpeg -hide_banner -loglevel warning -nostats \
      -rtsp_transport tcp -fflags +genpts+igndts -use_wallclock_as_timestamps 1 \
      -i "rtsp://127.0.0.1:8554/$PATH_NAME" \
      -c copy -f flv -flvflags no_duration_filesize \
      -rw_timeout 20000000 \
      -progress "$PROGRESS" \
      "$TARGET" >>/var/log/streamclip-relay.log 2>&1 &
    FF_PID=$!
    LAST=0
    STALL=0
    while kill -0 "$FF_PID" 2>/dev/null; do
      sleep 2
      CUR=$(sed -n 's/^total_size=//p' "$PROGRESS" 2>/dev/null | tail -1)
      case "$CUR" in
        ''|*[!0-9]*) CUR=0 ;;
      esac
      if [ "$CUR" -gt "$LAST" ]; then
        LAST=$CUR
        STALL=0
      else
        STALL=$((STALL + 2))
      fi
      MAX_STALL=20
      [ "$LAST" -eq 0 ] && MAX_STALL=30
      if [ "$STALL" -ge "$MAX_STALL" ]; then
        echo "relay reconnect path=$PATH_NAME bytes=$LAST stall=$STALL" >&2
        kill -TERM "$FF_PID" 2>/dev/null || true
        sleep 1
        kill -KILL "$FF_PID" 2>/dev/null || true
        break
      fi
    done
    wait "$FF_PID" 2>/dev/null || echo "relay push ended path=$PATH_NAME" >&2
    # OBS gone: stop republishing publisher_ready. A stall while the path is
    # still ready (spot push died) keeps looping.
    if ! python3 - "$PATH_NAME" <<'PY'
import json, sys, urllib.request
name = sys.argv[1]
try:
    with urllib.request.urlopen("http://127.0.0.1:9997/v3/paths/list", timeout=2) as resp:
        data = json.load(resp)
except Exception:
    sys.exit(0)
for item in data.get("items") or []:
    if item.get("name") == name and item.get("ready"):
        sys.exit(0)
sys.exit(1)
PY
    then
      echo "relay publisher gone path=$PATH_NAME" >&2
      exit 0
    fi
    sleep 2
  done
    RELAY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-relay
    chmod +x /usr/local/bin/streamclip-edge-relay

    cat > /usr/local/bin/streamclip-edge-on-ready <<ONREADY
    #!/bin/bash
    mkdir -p /var/run/streamclip
    export HOOK='$HOOK' EVENT_URL='$EVENT_URL' RELAY_URL='$RELAY_URL'
    nohup /usr/local/bin/streamclip-edge-relay "\$1" >>/var/log/streamclip-relay.log 2>&1 &
    ONREADY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-on-ready
    chmod +x /usr/local/bin/streamclip-edge-on-ready

    cat > /usr/local/bin/streamclip-edge-on-not-ready <<OFFREADY
    #!/bin/bash
    PATH_NAME="\$1"
    SAFE=\$(echo "\$PATH_NAME" | tr '/:' '__')
    PIDFILE="/var/run/streamclip/relay_\$SAFE.pid"
    if [ -f "\$PIDFILE" ]; then
      kill "\$(cat "\$PIDFILE")" 2>/dev/null || true
      rm -f "\$PIDFILE"
    fi
    pkill -f "ffmpeg.*(rtmp|rtsp).*\$PATH_NAME" 2>/dev/null || true
    curl -fsS -X POST -H Content-Type:application/json \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"publisher_disconnect\",\"path\":\"\$PATH_NAME\",\"protocol\":\"rtmp\"}" \
      "$EVENT_URL" || true
    OFFREADY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-on-not-ready
    chmod +x /usr/local/bin/streamclip-edge-on-not-ready

    cat > /etc/mediamtx/mediamtx.yml <<YAML
    logLevel: info
    # 1080p (~6–8 Mbit) + GOP 2s: default 512 overflows reader queues (VLC preview / relay).
    # Power of 2 only. 2048 ≈ 4× default — room for one full keyframe interval under burst.
    writeQueueSize: 2048
    readTimeout: 60s
    writeTimeout: 60s
    rtmp: yes
    rtmpAddress: :1935
    srt: yes
    srtAddress: :8890
    webrtc: no
    # Local HLS for dashboard preview (proxied on :8080; not public).
    hls: yes
    hlsAddress: 127.0.0.1:8888
    hlsAlwaysRemux: yes
    hlsSegmentCount: 7
    hlsSegmentDuration: 1s
    rtsp: yes
    rtspAddress: :8554
    authMethod: http
    authHTTPAddress: $${AUTH_URL}?ingest_secret=$${HOOK}
    pathDefaults:
      runOnReady: /usr/local/bin/streamclip-edge-on-ready \$MTX_PATH
      runOnNotReady: /usr/local/bin/streamclip-edge-on-not-ready \$MTX_PATH
    paths:
      all_others:
    YAML
    sed -i 's/^    //' /etc/mediamtx/mediamtx.yml

    cat > /usr/local/bin/streamclip-edge-hls.py <<'PROXY'
    #!/usr/bin/env python3
    import hashlib, hmac, os, re, time, urllib.error, urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse
    PORT = int(os.environ.get("STREAMCLIP_HLS_PORT", "8080"))
    UPSTREAM = os.environ.get("STREAMCLIP_HLS_UPSTREAM", "http://127.0.0.1:8888")
    SAFE = re.compile(r"^[A-Za-z0-9._/\\-]+$")
    HOOK = (os.environ.get("HOOK") or "").strip()
    def _ok(handler, q):
        if not HOOK: return True
        h = (handler.headers.get("X-Streamclip-Ingest-Secret") or "").strip()
        if h and hmac.compare_digest(h, HOOK): return True
        tok = (q.get("token") or [None])[0]
        if not tok or not str(tok).startswith("pb."): return False
        parts = str(tok).split(".")
        if len(parts) != 4: return False
        _, pid, exp_s, sig = parts
        try: exp = int(exp_s)
        except ValueError: return False
        if exp < int(time.time()): return False
        expect = hmac.new(HOOK.encode(), f"{pid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expect)
    class H(BaseHTTPRequestHandler):
        def log_message(self, *_a): return
        def do_GET(self):
            u = urlparse(self.path); q = parse_qs(u.query)
            if u.path in ("/health", "/"):
                b = b'{"ok":true,"service":"edge-hls"}'
                self.send_response(200); self.send_header("Content-Type","application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            if not u.path.startswith("/hls/"):
                self.send_response(404); self.end_headers(); return
            if not _ok(self, q):
                self.send_response(401); self.end_headers(); return
            sub = u.path[len("/hls/"):]
            if not sub or ".." in sub or not SAFE.match(sub):
                self.send_response(404); self.end_headers(); return
            try:
                with urllib.request.urlopen(f"{UPSTREAM.rstrip('/')}/{sub}", timeout=8) as r:
                    data = r.read(); ct = r.headers.get("Content-Type") or "application/octet-stream"
                self.send_response(200); self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control","no-store")
                self.end_headers(); self.wfile.write(data)
            except urllib.error.HTTPError as e:
                body = e.read() if e.fp else b""
                self.send_response(e.code); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except Exception:
                self.send_response(502); self.end_headers()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    PROXY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-hls.py
    chmod +x /usr/local/bin/streamclip-edge-hls.py
    mkdir -p /etc/streamclip
    printf 'HOOK=%s\n' "$HOOK" > /etc/streamclip/edge-hls.env

    cat > /etc/systemd/system/mediamtx.service <<'UNIT'
    [Unit]
    Description=STREAMCLIP edge MediaMTX
    After=network-online.target
    Wants=network-online.target
    [Service]
    Type=simple
    ExecStart=/usr/local/bin/mediamtx /etc/mediamtx/mediamtx.yml
    Restart=always
    RestartSec=3
    [Install]
    WantedBy=multi-user.target
    UNIT
    sed -i 's/^    //' /etc/systemd/system/mediamtx.service

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
    sed -i 's/^    //' /etc/systemd/system/streamclip-edge-hls.service
    systemctl daemon-reload
    systemctl enable --now mediamtx
    systemctl enable --now streamclip-edge-hls
    sleep 2
    ss -lntp | grep -E '1935|8080' > /dev/console || true
  EOF
}

resource "aws_instance" "ingest" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  subnet_id                   = element(data.aws_subnets.default.ids, 0)
  vpc_security_group_ids      = [aws_security_group.ingest.id]
  iam_instance_profile        = aws_iam_instance_profile.ingest.name
  associate_public_ip_address = true
  user_data                   = local.userdata
  user_data_replace_on_change = true

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = "terminate"
      }
    }
  }

  tags = {
    Name = var.name
    Role = "ingest"
  }
}

resource "aws_eip" "ingest" {
  count    = var.allocate_eip ? 1 : 0
  instance = aws_instance.ingest.id
  domain   = "vpc"
  tags     = { Name = "${var.name}-eip" }
}

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
        ]
        Resource = ["*"]
      },
    ]
  })
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
    # Shared edge (native MediaMTX): one RTMP URL for all OBS clients, ffmpeg
    # relay to each org's dedicated compute spot.
    set -eo pipefail
    dnf install -y ffmpeg || echo "ffmpeg unavailable"
    mkdir -p /etc/mediamtx /var/run/streamclip /usr/local/bin
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
    PATH_NAME="$1"
    SAFE=$(echo "$PATH_NAME" | tr '/:' '__')
    PIDFILE="/var/run/streamclip/relay_$${SAFE}.pid"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      exit 0
    fi
    echo $$ > "$PIDFILE"
    trap 'rm -f "$PIDFILE"' EXIT
    TARGET=""
    for _ in $(seq 1 60); do
      RESP=$(curl -fsS -G -H "X-Streamclip-Ingest-Secret: $HOOK" \
        --data-urlencode "path=$PATH_NAME" "$RELAY_URL" || true)
      TARGET=$(printf '%s' "$RESP" | sed -n 's/.*"rtmp_push_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      STATUS=$(printf '%s' "$RESP" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
      if [ "$STATUS" = "ready" ] && [ -n "$TARGET" ]; then
        break
      fi
      sleep 3
    done
    if [ -z "$TARGET" ]; then
      echo "relay target unavailable for $PATH_NAME" >&2
      exit 1
    fi
    curl -fsS -X POST -H Content-Type:application/json \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"publisher_ready\",\"path\":\"$PATH_NAME\",\"protocol\":\"rtmp\"}" \
      "$EVENT_URL" || true
    exec ffmpeg -hide_banner -loglevel warning -rw_timeout 15000000 \
      -i "rtmp://127.0.0.1/$PATH_NAME" -c copy -f flv "$TARGET"
    RELAY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-relay
    chmod +x /usr/local/bin/streamclip-edge-relay

    cat > /usr/local/bin/streamclip-edge-on-ready <<ONREADY
    #!/bin/bash
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
      pkill -f "ffmpeg.*rtmp://127.0.0.1/\$PATH_NAME" 2>/dev/null || true
      rm -f "\$PIDFILE"
    fi
    curl -fsS -X POST -H Content-Type:application/json \
      -H "X-Streamclip-Ingest-Secret: $HOOK" \
      -d "{\"event\":\"publisher_disconnect\",\"path\":\"\$PATH_NAME\",\"protocol\":\"rtmp\"}" \
      "$EVENT_URL" || true
    OFFREADY
    sed -i 's/^    //' /usr/local/bin/streamclip-edge-on-not-ready
    chmod +x /usr/local/bin/streamclip-edge-on-not-ready

    cat > /etc/mediamtx/mediamtx.yml <<YAML
    logLevel: info
    rtmp: yes
    rtmpAddress: :1935
    srt: yes
    srtAddress: :8890
    webrtc: no
    hls: no
    rtsp: no
    authMethod: http
    authHTTPAddress: $${AUTH_URL}?ingest_secret=$${HOOK}
    pathDefaults:
      runOnReady: /usr/local/bin/streamclip-edge-on-ready \$MTX_PATH
      runOnNotReady: /usr/local/bin/streamclip-edge-on-not-ready \$MTX_PATH
    paths:
      all_others:
    YAML
    sed -i 's/^    //' /etc/mediamtx/mediamtx.yml

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
    systemctl daemon-reload
    systemctl enable --now mediamtx
    sleep 2
    ss -lntp | grep 1935 > /dev/console || true
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

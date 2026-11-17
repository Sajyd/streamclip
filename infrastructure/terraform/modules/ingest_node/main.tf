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
  userdata = <<-EOF
    #!/bin/bash
    set -euo pipefail
    # AL2023 already ships curl-minimal; do not install the conflicting `curl` package.
    dnf install -y docker
    # ffmpeg is not always in AL2023 base repos; MediaMTX must start anyway.
    dnf install -y ffmpeg || echo "ffmpeg unavailable in repos; install later for segment loop"
    systemctl enable --now docker
    command -v curl >/dev/null || command -v curl-minimal >/dev/null
    mkdir -p /etc/mediamtx /var/lib/streamclip/segments
    cat >/etc/mediamtx/mediamtx.yml <<'YAML'
    logLevel: info
    rtmp: yes
    rtmpAddress: :1935
    srt: yes
    srtAddress: :8890
    webrtc: no
    hls: no
    rtsp: no
    authMethod: http
    authHTTPAddress: ${var.api_auth_url}
    authHTTPAdditionalHeaders:
      X-Streamclip-Ingest-Secret: "${var.ingest_hook_secret}"
    pathDefaults:
      runOnReady: >
        curl -fsS -X POST
        -H "Content-Type: application/json"
        -H "X-Streamclip-Ingest-Secret: ${var.ingest_hook_secret}"
        -d "{\"event\":\"publisher_ready\",\"path\":\"$MTX_PATH\",\"protocol\":\"rtmp\"}"
        ${local.event_url}
      runOnNotReady: >
        curl -fsS -X POST
        -H "Content-Type: application/json"
        -H "X-Streamclip-Ingest-Secret: ${var.ingest_hook_secret}"
        -d "{\"event\":\"publisher_disconnect\",\"path\":\"$MTX_PATH\",\"protocol\":\"rtmp\"}"
        ${local.event_url}
    paths:
      "live/~path":
        source: publisher
    YAML
    docker run -d --name mediamtx --restart unless-stopped \
      -p 1935:1935 -p 8890:8890/udp \
      -v /etc/mediamtx/mediamtx.yml:/mediamtx.yml:ro \
      bluenviron/mediamtx:1.11.3
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

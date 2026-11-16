# Private media bucket.
#
# Nothing in this bucket is ever public: clients only receive short-lived
# pre-signed URLs issued by the API after an ownership check.
#
# Versioning is deliberately left off. An erased account must really be
# erased (GDPR), and keeping deleted media as noncurrent versions would both
# break that promise and add storage cost.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name
  tags   = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    # ACLs disabled: access is governed by policies only.
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyOutdatedTls"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.bucket.json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

# Lifecycle rules are evaluated once a day by S3: an object expiring "after
# 1 day" is removed between 24 and 48 hours after its creation.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "expire-temporary-objects"
    status = "Enabled"

    filter {
      prefix = var.temporary_prefix
    }

    expiration {
      days = var.temporary_expiration_days
    }
  }

  # Safety net behind the application, which deletes these objects itself
  # when they expire: tenant keys cannot be matched by prefix, so short-lived
  # objects (personal-data exports) carry a tag.
  rule {
    id     = "expire-short-retention-objects"
    status = "Enabled"

    filter {
      tag {
        key   = var.short_retention_tag.key
        value = var.short_retention_tag.value
      }
    }

    expiration {
      days = var.short_retention_expiration_days
    }
  }
}

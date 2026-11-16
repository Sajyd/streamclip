# Identity used by the API at runtime: object storage only, application
# prefixes only. It cannot read or change any other AWS resource, nor the
# bucket's own configuration.
#
# The access key is NOT managed here, so that no secret ever lands in the
# Terraform state: it is issued and rotated with scripts/aws-runtime-key.sh.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }
}

resource "aws_iam_user" "this" {
  name = var.name
  path = var.path
  tags = var.tags
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "ListApplicationPrefixes"
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [for prefix in var.object_prefixes : "${prefix}*"]
    }
  }

  statement {
    sid = "ManageApplicationObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:PutObjectTagging",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = [for prefix in var.object_prefixes : "${var.bucket_arn}/${prefix}*"]
  }
}

resource "aws_iam_user_policy" "this" {
  name   = "object-storage"
  user   = aws_iam_user.this.name
  policy = data.aws_iam_policy_document.this.json
}

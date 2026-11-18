# Production environment.
#
# Run through scripts/terraform.sh, which supplies the remote state bucket
# and the variables below from the local, git-ignored .env file:
#
#   scripts/terraform.sh production plan
#   scripts/terraform.sh production apply

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }

  # The state bucket is passed at init time (-backend-config): no
  # account-specific value is committed.
  backend "s3" {
    key          = "production/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

locals {
  environment = "production"

  tags = {
    Project     = "streamclip"
    Environment = local.environment
    ManagedBy   = "terraform"
  }
}

# The media bucket existed before this configuration: it is adopted rather
# than created. These blocks are no-ops once the resources are in the state.
import {
  to = module.storage.aws_s3_bucket.this
  id = var.bucket_name
}

import {
  to = module.storage.aws_s3_bucket_ownership_controls.this
  id = var.bucket_name
}

import {
  to = module.storage.aws_s3_bucket_server_side_encryption_configuration.this
  id = var.bucket_name
}

module "storage" {
  source = "../../modules/storage"

  bucket_name = var.bucket_name
}

module "runtime_identity" {
  source = "../../modules/runtime_identity"

  name       = "streamclip-${local.environment}-runtime"
  bucket_arn = module.storage.bucket_arn
}

module "ingest_node" {
  count  = var.enable_ingest_node ? 1 : 0
  source = "../../modules/ingest_node"

  name               = "streamclip-${local.environment}-ingest"
  bucket_arn         = module.storage.bucket_arn
  api_auth_url       = var.ingest_api_auth_url
  api_event_url      = var.ingest_api_event_url != "" ? var.ingest_api_event_url : replace(var.ingest_api_auth_url, "/auth", "/event")
  ingest_hook_secret = var.ingest_hook_secret
  instance_type      = "t4g.small"
  # Shared OBS entrypoint. Spot reclaim in eu-north-1b left the Elastic IP unattached.
  use_spot           = false
  availability_zone  = "eu-north-1a"
  allocate_eip       = true
}

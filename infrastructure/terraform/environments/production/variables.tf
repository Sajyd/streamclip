variable "aws_region" {
  description = "Region of the production resources (S3_REGION in .env)."
  type        = string
}

variable "bucket_name" {
  description = "Existing private media bucket to adopt (S3_BUCKET in .env)."
  type        = string
}

variable "enable_ingest_node" {
  description = "Launch a MediaMTX EC2 ingest node (default VPC). Off until secrets are ready."
  type        = bool
  default     = false
}

variable "ingest_api_auth_url" {
  description = "POST URL for MediaMTX auth (…/api/v1/ingest/hooks/auth)."
  type        = string
  default     = ""
}

variable "ingest_hook_secret" {
  description = "Shared secret for MediaMTX → API hooks."
  type        = string
  default     = ""
  sensitive   = true
}

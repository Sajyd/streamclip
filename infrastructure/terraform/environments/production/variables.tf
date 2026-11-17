variable "aws_region" {
  description = "Region of the production resources (S3_REGION in .env)."
  type        = string
}

variable "bucket_name" {
  description = "Existing private media bucket to adopt (S3_BUCKET in .env)."
  type        = string
}

variable "enable_ingest_node" {
  description = "Shared edge MediaMTX: one RTMP URL for all OBS clients; relays to per-org spots."
  type        = bool
  default     = true
}

variable "ingest_api_auth_url" {
  description = "POST URL for MediaMTX auth (.../api/v1/ingest/hooks/auth)."
  type        = string
  default     = ""
}

variable "ingest_api_event_url" {
  description = "POST URL for MediaMTX events (.../api/v1/ingest/hooks/event)."
  type        = string
  default     = ""
}

variable "ingest_hook_secret" {
  description = "Shared secret for MediaMTX → API hooks."
  type        = string
  default     = ""
  sensitive   = true
}

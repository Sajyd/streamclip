variable "name" {
  type        = string
  description = "Resource name prefix (e.g. streamclip-production-ingest)."
}

variable "bucket_arn" {
  type        = string
  description = "Media bucket ARN (tmp/ writes for future segment upload)."
}

variable "api_auth_url" {
  type        = string
  description = "Full URL of POST /api/v1/ingest/hooks/auth on the control plane."
}

variable "api_event_url" {
  type        = string
  description = "Full URL of POST /api/v1/ingest/hooks/event on the control plane."
  default     = ""
}

variable "ingest_hook_secret" {
  type        = string
  sensitive   = true
  description = "Shared secret sent as x-streamclip-ingest-secret."
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
}

variable "use_spot" {
  type    = bool
  default = true
}

variable "allocate_eip" {
  type    = bool
  default = true
}

variable "ssh_cidr_blocks" {
  type    = list(string)
  default = []
}

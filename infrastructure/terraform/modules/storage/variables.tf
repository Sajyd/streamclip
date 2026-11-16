variable "bucket_name" {
  description = "Name of the private media bucket."
  type        = string
}

variable "temporary_prefix" {
  description = "Key prefix of processing buffers, removed automatically."
  type        = string
  default     = "tmp/"
}

variable "temporary_expiration_days" {
  description = "Days after which objects under the temporary prefix expire."
  type        = number
  default     = 1

  validation {
    condition     = var.temporary_expiration_days >= 1
    error_message = "S3 lifecycle rules cannot expire objects in less than one day."
  }
}

variable "short_retention_tag" {
  description = "Object tag marking short-lived objects stored under tenant prefixes. Must match the backend (app/storage/s3.py)."
  type = object({
    key   = string
    value = string
  })
  default = {
    key   = "streamclip-retention"
    value = "short"
  }
}

variable "short_retention_expiration_days" {
  description = "Days after which tagged short-retention objects expire. Must exceed the application's own retention (DATA_EXPORT_TTL_DAYS)."
  type        = number
  default     = 10
}

variable "tags" {
  description = "Tags applied to the bucket."
  type        = map(string)
  default     = {}
}

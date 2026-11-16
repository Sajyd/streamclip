variable "name" {
  description = "Name of the IAM user the API authenticates as."
  type        = string
}

variable "path" {
  description = "IAM path grouping the project's identities."
  type        = string
  default     = "/streamclip/"
}

variable "bucket_arn" {
  description = "ARN of the media bucket the identity may use."
  type        = string
}

variable "object_prefixes" {
  description = "Key prefixes the identity may list, read, write and delete."
  type        = list(string)
  default     = ["tenants/", "tmp/"]
}

variable "tags" {
  description = "Tags applied to the IAM user."
  type        = map(string)
  default     = {}
}

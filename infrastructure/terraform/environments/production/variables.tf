variable "aws_region" {
  description = "Region of the production resources (S3_REGION in .env)."
  type        = string
}

variable "bucket_name" {
  description = "Existing private media bucket to adopt (S3_BUCKET in .env)."
  type        = string
}

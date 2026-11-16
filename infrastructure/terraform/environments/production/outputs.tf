output "bucket_name" {
  description = "Media bucket (S3_BUCKET)."
  value       = module.storage.bucket_name
}

output "bucket_region" {
  description = "Region of the media bucket (S3_REGION)."
  value       = module.storage.bucket_region
}

output "runtime_user_name" {
  description = "IAM user the API authenticates as; issue its key with scripts/aws-runtime-key.sh."
  value       = module.runtime_identity.user_name
}

output "runtime_user_arn" {
  description = "ARN of the runtime IAM user."
  value       = module.runtime_identity.user_arn
}

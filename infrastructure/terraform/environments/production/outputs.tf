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

output "ingest_public_ip" {
  description = "Public IP of the MediaMTX node (null when disabled)."
  value       = try(module.ingest_node[0].public_ip, null)
}

output "ingest_public_host" {
  description = "Hostname/IP to set as INGEST_PUBLIC_HOST."
  value       = try(module.ingest_node[0].public_ip, null)
}

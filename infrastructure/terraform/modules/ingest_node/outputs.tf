output "instance_id" {
  value = aws_instance.ingest.id
}

output "public_ip" {
  value = try(aws_eip.ingest[0].public_ip, aws_instance.ingest.public_ip)
}

output "public_dns" {
  value = aws_instance.ingest.public_dns
}

output "security_group_id" {
  value = aws_security_group.ingest.id
}

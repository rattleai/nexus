# ──────────────────────────────────────────────────────────────
# Outputs
# ──────────────────────────────────────────────────────────────

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "alb_dns_name" {
  description = "ALB DNS name — point your domain CNAME here"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID for Route 53 alias records"
  value       = aws_lb.main.zone_id
}

output "rds_endpoint" {
  description = "RDS writer endpoint"
  value       = aws_db_instance.main.endpoint
}



output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_replication_group.main.port
}

output "uploads_bucket" {
  description = "S3 uploads bucket name"
  value       = aws_s3_bucket.uploads.id
}

output "uploads_bucket_arn" {
  description = "S3 uploads bucket ARN"
  value       = aws_s3_bucket.uploads.arn
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "api_service_name" {
  description = "ECS API service name"
  value       = aws_ecs_service.api.name
}

output "secrets_arn" {
  description = "Secrets Manager ARN for app config"
  value       = aws_secretsmanager_secret.app_config.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for ECS tasks"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "database_url_hint" {
  description = "DATABASE_URL pattern (actual URL with password is in Secrets Manager)"
  value       = "postgresql+asyncpg://app_user:<password>@${aws_db_instance.main.endpoint}/${var.db_name}?ssl=require"
  sensitive   = true
}

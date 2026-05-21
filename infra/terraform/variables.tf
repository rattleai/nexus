# ──────────────────────────────────────────────────────────────
# Input Variables
# ──────────────────────────────────────────────────────────────

# ── General ──────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "dr_region" {
  description = <<-EOT
    Secondary AWS region for disaster-recovery cross-region replication
    (RDS automated backups, S3 replica buckets). Leave empty ("") to
    disable all DR resources — they are gated on `var.dr_region != ""`.
  EOT
  type        = string
  default     = ""
}

variable "dr_s3_bucket_arn" {
  description = <<-EOT
    Pre-existing S3 bucket ARN in the DR region used as the replication
    target for the primary uploads bucket. Required when var.dr_region
    is set; otherwise unused (the replication resources have count=0).
    Provision the bucket in the DR account/region out of band.
  EOT
  type        = string
  default     = ""
}

variable "environment" {
  description = "Deployment environment (prod, staging)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging"], var.environment)
    error_message = "environment must be prod or staging"
  }
}

# ── Networking ───────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "domain_name" {
  description = "Primary domain name (e.g. example.com)"
  type        = string
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for the domain"
  type        = string
  default     = ""
}

# ── Database ─────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 50
}

variable "db_max_allocated_storage" {
  description = "Maximum storage autoscaling limit in GB"
  type        = number
  default     = 200
}

variable "db_name" {
  description = "Name of the application database"
  type        = string
  default     = "app"
}

variable "db_master_username" {
  description = "Master username for RDS (superuser — migrations only)"
  type        = string
  default     = "app_admin"
}

# ── Redis ────────────────────────────────────────────────────

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t4g.small"
}

# ── ECS / Container ─────────────────────────────────────────

variable "container_image" {
  description = "Container image URI (e.g. ghcr.io/org/nxs:latest)"
  type        = string
}

variable "api_cpu" {
  description = "CPU units for API task (1 vCPU = 1024)"
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Memory in MiB for API task"
  type        = number
  default     = 2048
}

variable "api_desired_count" {
  description = "Desired number of API tasks"
  type        = number
  default     = 2
}

variable "api_max_count" {
  description = "Maximum number of API tasks for autoscaling"
  type        = number
  default     = 4
}

variable "worker_cpu" {
  description = "CPU units for worker task"
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "Memory in MiB for worker task"
  type        = number
  default     = 2048
}

variable "beat_cpu" {
  description = "CPU units for beat scheduler task"
  type        = number
  default     = 256
}

variable "beat_memory" {
  description = "Memory in MiB for beat scheduler task"
  type        = number
  default     = 512
}

# ── Application Secrets ─────────────────────────────────────
# These are passed via terraform.tfvars or environment variables.
# They populate AWS Secrets Manager; containers read from there.

variable "app_secret_key" {
  description = "Application SECRET_KEY"
  type        = string
  sensitive   = true
}

variable "app_encryption_key" {
  description = "Data-at-rest ENCRYPTION_KEY"
  type        = string
  sensitive   = true
}

variable "app_webhook_signing_key" {
  description = "WEBHOOK_SIGNING_KEY for HMAC signatures"
  type        = string
  sensitive   = true
}

variable "app_admin_key" {
  description = "ADMIN_KEY for admin endpoints"
  type        = string
  sensitive   = true
}

variable "stripe_secret_key" {
  description = "Stripe secret key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "brevo_api_key" {
  description = "Brevo (Sendinblue) API key for transactional email"
  type        = string
  sensitive   = true
  default     = ""
}

variable "cors_origins" {
  description = "Comma-separated list of allowed CORS origins"
  type        = string
  default     = ""
}

# ── S3 ───────────────────────────────────────────────────────

variable "uploads_bucket_name" {
  description = "S3 bucket name for file uploads (must be globally unique)"
  type        = string
  default     = ""
}

# ── Monitoring ─────────────────────────────────────────────────

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications (leave empty to skip)"
  type        = string
  default     = ""
}

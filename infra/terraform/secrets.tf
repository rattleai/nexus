# ──────────────────────────────────────────────────────────────
# Secrets Manager — Application configuration
# ──────────────────────────────────────────────────────────────
#
# All sensitive values are stored as a single JSON secret.
# ECS task definitions reference individual keys via
# the `valueFrom` syntax: <secret_arn>:<json_key>::
#
# After initial deploy, rotate secrets via the AWS console or CLI:
#   aws secretsmanager update-secret --secret-id <arn> \
#     --secret-string '{"SECRET_KEY":"...", ...}'

resource "aws_secretsmanager_secret" "app_config" {
  name                    = "${local.name_prefix}/app/config"
  description             = "CAD Price application secrets (referenced by ECS tasks)"
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-app-config" }
}

resource "aws_secretsmanager_secret_version" "app_config" {
  secret_id = aws_secretsmanager_secret.app_config.id

  secret_string = jsonencode({
    SECRET_KEY             = var.app_secret_key
    ENCRYPTION_KEY         = var.app_encryption_key
    WEBHOOK_SIGNING_KEY    = var.app_webhook_signing_key
    ADMIN_KEY              = var.app_admin_key
    DB_APP_USER_PASSWORD   = random_password.db_app_user.result
    DB_MASTER_PASSWORD     = random_password.db_master.result
    # Full connection URLs with credentials — kept in Secrets Manager, never in env vars
    DATABASE_URL           = "postgresql+asyncpg://app_user:${random_password.db_app_user.result}@${aws_db_instance.main.endpoint}/${var.db_name}?ssl=require"
    DATABASE_SYNC_URL      = "postgresql://app_user:${random_password.db_app_user.result}@${aws_db_instance.main.endpoint}/${var.db_name}?sslmode=require"
    REDIS_URL              = "rediss://:${random_password.redis_auth.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    STRIPE_SECRET_KEY      = var.stripe_secret_key
    STRIPE_WEBHOOK_SECRET  = var.stripe_webhook_secret
    BREVO_API_KEY          = var.brevo_api_key
    REDIS_AUTH_TOKEN       = random_password.redis_auth.result
  })

  lifecycle {
    # After initial creation, secrets may be rotated out-of-band.
    # Remove this if you want Terraform to always overwrite.
    ignore_changes = [secret_string]
  }
}

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

data "aws_prefix_list" "secretsmanager" {
  filter {
    name   = "prefix-list-name"
    values = ["com.amazonaws.${var.aws_region}.secretsmanager"]
  }
}

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

# ──────────────────────────────────────────────────────────────
# Secrets Rotation — Automated rotation for DB passwords
# ──────────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret_rotation" "db_master_password" {
  secret_id           = aws_secretsmanager_secret.db_master_password.id
  rotation_lambda_arn = aws_lambda_function.secret_rotation.arn

  rotation_rules {
    # AWS provider v5 enforces: pick exactly one of
    # automatically_after_days or schedule_expression. schedule_expression
    # is more flexible (cron / rate), so we keep it and drop the redundant
    # day count.
    schedule_expression = "rate(30 days)"
  }
}

# IAM role for the rotation Lambda
resource "aws_iam_role" "secret_rotation_lambda" {
  name = "${local.name_prefix}-secret-rotation-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "secret_rotation_lambda" {
  name = "${local.name_prefix}-secret-rotation-policy"
  role = aws_iam_role.secret_rotation_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecretVersionStage",
        ]
        Resource = [
          aws_secretsmanager_secret.db_master_password.arn,
          aws_secretsmanager_secret.app_config.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface", "ec2:DescribeNetworkInterfaces"]
        Resource = "*"
      },
    ]
  })
}

# Dedicated security group for the rotation Lambda — no inbound rules,
# outbound restricted to RDS (5432) and Secrets Manager (443 via VPC endpoint).
resource "aws_security_group" "secret_rotation_lambda" {
  name_prefix = "${local.name_prefix}-rotation-lambda-"
  description = "SG for Secrets Manager rotation Lambda"
  vpc_id      = aws_vpc.main.id

  egress {
    description     = "PostgreSQL to RDS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.rds.id]
  }

  egress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_prefix_list.secretsmanager.id]
    description     = "HTTPS to Secrets Manager VPC endpoint only"
  }

  lifecycle { create_before_destroy = true }
  tags = { Name = "${local.name_prefix}-rotation-lambda-sg" }
}

resource "aws_lambda_function" "secret_rotation" {
  function_name = "${local.name_prefix}-secret-rotation"
  description   = "Rotates RDS master password in Secrets Manager"
  role          = aws_iam_role.secret_rotation_lambda.arn
  handler       = "index.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 128

  # The rotation Lambda code is packaged separately by the deploy
  # pipeline (scripts/build_lambda_secret_rotation.sh) before
  # `terraform apply`. The zip is intentionally not committed; CI's
  # `terraform validate` therefore can't read it, so the hash falls
  # back through `try()` to a sentinel that satisfies the type check.
  # Apply still fails loudly if the zip is missing because `filename`
  # is checked at plan/apply time without any try() wrapper.
  filename         = "${path.module}/lambda/secret_rotation.zip"
  source_code_hash = try(
    filebase64sha256("${path.module}/lambda/secret_rotation.zip"),
    "validate-only-placeholder",
  )

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    # Lambda needs its own SG — not the RDS SG — with no inbound rules
    # and outbound restricted to RDS (5432) and Secrets Manager (443).
    security_group_ids = [aws_security_group.secret_rotation_lambda.id]
  }

  environment {
    variables = {
      RDS_ENDPOINT = aws_db_instance.main.endpoint
      DB_NAME      = var.db_name
    }
  }

  tags = { Name = "${local.name_prefix}-secret-rotation" }
}

resource "aws_lambda_permission" "secret_rotation" {
  statement_id  = "AllowSecretsManagerInvocation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.secret_rotation.function_name
  principal     = "secretsmanager.amazonaws.com"
  source_arn    = aws_secretsmanager_secret.db_master_password.arn
}

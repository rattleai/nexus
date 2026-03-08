# ──────────────────────────────────────────────────────────────
# ECS Fargate — API (2-4), Worker (1), Beat (1)
# ──────────────────────────────────────────────────────────────

# ── Cluster ──────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${local.name_prefix}-cluster" }
}

# ── CloudWatch Log Group ─────────────────────────────────────

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${local.name_prefix}"
  retention_in_days = 30
}

# ── ECS Task Security Group ─────────────────────────────────

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${local.name_prefix}-ecs-"
  description = "ECS Fargate tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }

  tags = { Name = "${local.name_prefix}-ecs-tasks-sg" }
}

# ── IAM: Task Execution Role (ECR pull, logs, secrets) ───────

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name_prefix}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_base" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "secrets-access"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
      ]
      Resource = [
        aws_secretsmanager_secret.app_config.arn,
        aws_secretsmanager_secret.db_master_password.arn,
      ]
    }]
  })
}

# ── IAM: Task Role (what the container can do at runtime) ────

resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "s3-uploads-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
      ]
      Resource = [
        aws_s3_bucket.uploads.arn,
        "${aws_s3_bucket.uploads.arn}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_secrets" {
  name = "secrets-read"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
      ]
      Resource = [
        aws_secretsmanager_secret.app_config.arn,
      ]
    }]
  })
}

# ── Container Environment (shared across all services) ───────

locals {
  # Non-sensitive env vars set directly on the container
  container_environment = [
    { name = "DEBUG", value = "false" },
    { name = "DATABASE_SSL_MODE", value = "require" },
    { name = "S3_BUCKET", value = aws_s3_bucket.uploads.id },
    { name = "S3_REGION", value = var.aws_region },
    { name = "CORS_ORIGINS", value = var.cors_origins != "" ? var.cors_origins : "https://${var.domain_name}" },
    { name = "AUTH_ENABLED", value = "true" },
    { name = "OTEL_ENABLED", value = "false" },
  ]

  # Sensitive values pulled from Secrets Manager at container start.
  # DATABASE_URL and REDIS_URL contain credentials — always use secrets.
  container_secrets = [
    { name = "SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:SECRET_KEY::" },
    { name = "ENCRYPTION_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:ENCRYPTION_KEY::" },
    { name = "WEBHOOK_SIGNING_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:WEBHOOK_SIGNING_KEY::" },
    { name = "ADMIN_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:ADMIN_KEY::" },
    { name = "DATABASE_URL", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:DATABASE_URL::" },
    { name = "DATABASE_SYNC_URL", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:DATABASE_SYNC_URL::" },
    { name = "REDIS_URL", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:REDIS_URL::" },
    { name = "STRIPE_SECRET_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:STRIPE_SECRET_KEY::" },
    { name = "STRIPE_WEBHOOK_SECRET", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:STRIPE_WEBHOOK_SECRET::" },
    { name = "BREVO_API_KEY", valueFrom = "${aws_secretsmanager_secret.app_config.arn}:BREVO_API_KEY::" },
  ]
}

# ── API Task Definition ──────────────────────────────────────

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = var.container_image
    essential = true

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    command = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

    environment = local.container_environment
    secrets     = local.container_secrets

    healthCheck = {
      command     = ["CMD-SHELL", "curl -sf http://localhost:8000/api/v1/health/live || exit 1"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])

  tags = { Name = "${local.name_prefix}-api-task" }
}

# ── API Service ──────────────────────────────────────────────

resource "aws_ecs_service" "api" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  depends_on = [aws_lb_listener.https]

  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = { Name = "${local.name_prefix}-api-service" }
}

# ── API Auto Scaling ─────────────────────────────────────────

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_max_count
  min_capacity       = var.api_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.name_prefix}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

# ── Worker Task Definition ───────────────────────────────────

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = var.container_image
    essential = true

    command = ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--concurrency=4"]

    environment = local.container_environment
    secrets     = local.container_secrets

    healthCheck = {
      command     = ["CMD-SHELL", "celery -A app.workers.celery_app inspect ping --timeout 5 || exit 1"]
      interval    = 30
      timeout     = 10
      retries     = 3
      startPeriod = 30
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])

  tags = { Name = "${local.name_prefix}-worker-task" }
}

# ── Worker Service ───────────────────────────────────────────

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = { Name = "${local.name_prefix}-worker-service" }
}

# ── Beat Task Definition ─────────────────────────────────────

resource "aws_ecs_task_definition" "beat" {
  family                   = "${local.name_prefix}-beat"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.beat_cpu
  memory                   = var.beat_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "beat"
    image     = var.container_image
    essential = true

    command = ["celery", "-A", "app.workers.celery_app", "beat", "--loglevel=info"]

    environment = local.container_environment
    secrets     = local.container_secrets

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "beat"
      }
    }
  }])

  tags = { Name = "${local.name_prefix}-beat-task" }
}

# ── Beat Service ─────────────────────────────────────────────

resource "aws_ecs_service" "beat" {
  name            = "${local.name_prefix}-beat"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.beat.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = { Name = "${local.name_prefix}-beat-service" }
}

# ──────────────────────────────────────────────────────────────
# RDS PostgreSQL 16 — Multi-AZ, encrypted, RLS-friendly
# ──────────────────────────────────────────────────────────────

# ── Subnet Group ─────────────────────────────────────────────

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-db-subnet-group" }
}

# ── Security Group ───────────────────────────────────────────

resource "aws_security_group" "rds" {
  name_prefix = "${local.name_prefix}-rds-"
  description = "RDS PostgreSQL — allow inbound from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle { create_before_destroy = true }

  tags = { Name = "${local.name_prefix}-rds-sg" }
}

# ── Parameter Group (RLS-friendly settings) ──────────────────

resource "aws_db_parameter_group" "main" {
  name_prefix = "${local.name_prefix}-pg16-"
  family      = "postgres16"
  description = "PostgreSQL 16 parameters for CAD Price (RLS-enabled)"

  # Row-Level Security requires non-superuser connections.
  # These parameters ensure RLS policies are enforced and
  # the app_user role works correctly.

  # Force SSL for all connections
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # Log slow queries (> 1 second)
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  # Connection limits — matches app pool sizing
  parameter {
    name  = "max_connections"
    value = "200"
  }

  # Shared buffers — 25% of instance memory is standard
  parameter {
    name  = "shared_buffers"
    value = "{DBInstanceClassMemory/4}"
  }

  # Work memory for complex queries (sorting, joins)
  parameter {
    name  = "work_mem"
    value = "65536"
  }

  # Enable pg_stat_statements for query performance monitoring
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "pg_stat_statements.track"
    value = "all"
  }

  # Log RLS-related configuration changes
  parameter {
    name  = "log_statement"
    value = "ddl"
  }

  # Noisy neighbor prevention: kill queries running longer than 30 seconds
  # Prevents one tenant's expensive query from starving the connection pool
  parameter {
    name  = "statement_timeout"
    value = "30000"
  }

  # Prevent individual queries from consuming excessive temp disk
  parameter {
    name  = "temp_file_limit"
    value = "1048576"  # 1 GB in KB
  }

  lifecycle { create_before_destroy = true }
}

# ── Master Password ──────────────────────────────────────────

resource "random_password" "db_master" {
  length  = 32
  special = false
}

resource "random_password" "db_app_user" {
  length  = 32
  special = false
}

# ── RDS Instance ─────────────────────────────────────────────

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-pg"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_master_username
  password = random_password.db_master.result

  multi_az               = true
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name

  # Backups
  backup_retention_period = 14
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:30-mon:05:30"

  # Protection
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-pg-final"
  copy_tags_to_snapshot     = true

  # Monitoring
  performance_insights_enabled    = true
  performance_insights_retention_period = 7
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn

  # Logging
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  # Avoid public access
  publicly_accessible = false

  tags = { Name = "${local.name_prefix}-pg" }
}

# ── Enhanced Monitoring IAM Role ─────────────────────────────

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name_prefix}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ── Store passwords in Secrets Manager ───────────────────────
# The master password is stored here. The app_user password is
# included in the app_config secret (see secrets.tf).

# ── Cross-Region Backup Replication (DR) ─────────────────

resource "aws_db_instance_automated_backups_replication" "dr" {
  count = var.dr_region != "" ? 1 : 0

  source_db_instance_arn = aws_db_instance.main.arn
  retention_period       = 14

  # Note: This resource must be created in the DR region.
  # Use a provider alias for the DR region in production.
}

# ── Store passwords in Secrets Manager ───────────────────
# The master password is stored here. The app_user password is
# included in the app_config secret (see secrets.tf).

resource "aws_secretsmanager_secret" "db_master_password" {
  name                    = "${local.name_prefix}/db/master-password"
  description             = "RDS master (superuser) password — for migrations only"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db_master_password" {
  secret_id     = aws_secretsmanager_secret.db_master_password.id
  secret_string = random_password.db_master.result
}

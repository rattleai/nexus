# ──────────────────────────────────────────────────────────────
# ElastiCache Redis 7 — Encryption in transit, single node
# ──────────────────────────────────────────────────────────────

# ── Subnet Group ─────────────────────────────────────────────

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.name_prefix}-redis"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-redis-subnet-group" }
}

# ── Security Group ───────────────────────────────────────────

resource "aws_security_group" "redis" {
  name_prefix = "${local.name_prefix}-redis-"
  description = "ElastiCache Redis — allow inbound from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from ECS"
    from_port       = 6379
    to_port         = 6379
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

  tags = { Name = "${local.name_prefix}-redis-sg" }
}

# ── Auth Token ───────────────────────────────────────────────

resource "random_password" "redis_auth" {
  length  = 64
  special = false
}

# ── Replication Group (single-node with failover ready) ──────

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "NEXUS Redis cluster"

  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.redis_node_type
  num_cache_clusters   = 1
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # Encryption
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  # Maintenance
  maintenance_window       = "tue:04:00-tue:05:00"
  snapshot_retention_limit = 3
  snapshot_window          = "02:00-03:00"
  auto_minor_version_upgrade = true

  # Parameters
  parameter_group_name = aws_elasticache_parameter_group.main.name

  tags = { Name = "${local.name_prefix}-redis" }
}

resource "aws_elasticache_parameter_group" "main" {
  name   = "${local.name_prefix}-redis7"
  family = "redis7"

  # Match docker-compose maxmemory-policy
  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
}

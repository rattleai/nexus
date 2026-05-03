# ──────────────────────────────────────────────────────────────
# Terraform State Bootstrap
#
# Creates the S3 bucket and DynamoDB table needed for remote
# state management. Run this ONCE before enabling the backend
# block in the root module.
#
# Usage:
#   cd infra/terraform/bootstrap
#   terraform init
#   terraform apply
#   # Then uncomment the backend block in ../main.tf
#   cd .. && terraform init -migrate-state
# ──────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "nxs"
      ManagedBy = "terraform-bootstrap"
    }
  }
}

variable "aws_region" {
  description = "AWS region for state resources"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "S3 bucket name for Terraform state"
  type        = string
  default     = "nxs-terraform-state"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name for state locking"
  type        = string
  default     = "nxs-terraform-locks"
}

# ── S3 Bucket for State ─────────────────────────────────

resource "aws_s3_bucket" "state" {
  bucket = var.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── DynamoDB Table for State Locking ────────────────────

resource "aws_dynamodb_table" "locks" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ── Outputs ─────────────────────────────────────────────

output "state_bucket_arn" {
  description = "ARN of the S3 state bucket"
  value       = aws_s3_bucket.state.arn
}

output "lock_table_arn" {
  description = "ARN of the DynamoDB lock table"
  value       = aws_dynamodb_table.locks.arn
}

output "backend_config" {
  description = "Backend configuration to paste into root main.tf"
  value = <<-EOT
    backend "s3" {
      bucket         = "${var.bucket_name}"
      key            = "prod/terraform.tfstate"
      region         = "${var.aws_region}"
      dynamodb_table = "${var.dynamodb_table_name}"
      encrypt        = true
    }
  EOT
}

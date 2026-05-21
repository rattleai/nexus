# ──────────────────────────────────────────────────────────────
# NEXUS SaaS Platform — Terraform Root Module
# ──────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state backend — requires bootstrap resources.
  # Run `cd infra/terraform/bootstrap && terraform apply` first,
  # then `cd .. && terraform init -migrate-state` to migrate.
  backend "s3" {
    bucket         = "nxs-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nxs-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "nxs"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Secondary provider for the DR region. Required because rds.tf references
# aws.dr_region for cross-region automated-backup replication (and s3.tf
# gates its DR bucket on var.dr_region). When dr_region is empty, the
# provider is still declared — with the primary region as a fallback — so
# `terraform validate` succeeds and the DR resources simply have count=0.
provider "aws" {
  alias  = "dr_region"
  region = var.dr_region != "" ? var.dr_region : var.aws_region

  default_tags {
    tags = {
      Project     = "nxs"
      Environment = var.environment
      ManagedBy   = "terraform"
      Role        = "dr"
    }
  }
}

# ── Data Sources ─────────────────────────────────────────────

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

# ── Locals ───────────────────────────────────────────────────

locals {
  name_prefix = "nxs-${var.environment}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)

  common_tags = {
    Project     = "nxs"
    Environment = var.environment
  }
}

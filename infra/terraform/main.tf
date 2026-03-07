# ──────────────────────────────────────────────────────────────
# CAD Price SaaS Platform — Terraform Root Module
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

  # Uncomment and configure for remote state
  # backend "s3" {
  #   bucket         = "cadprice-terraform-state"
  #   key            = "prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "cadprice-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cadprice"
      Environment = var.environment
      ManagedBy   = "terraform"
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
  name_prefix = "cadprice-${var.environment}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)

  common_tags = {
    Project     = "cadprice"
    Environment = var.environment
  }
}

# ──────────────────────────────────────────────────────────────
# S3 — File uploads with versioning, lifecycle, encryption
# ──────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "uploads" {
  bucket = var.uploads_bucket_name != "" ? var.uploads_bucket_name : "${local.name_prefix}-uploads-${data.aws_caller_identity.current.account_id}"

  tags = { Name = "${local.name_prefix}-uploads" }
}

# ── Versioning ───────────────────────────────────────────────

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ── Server-Side Encryption ──────────────────────────────────

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# ── Block Public Access ─────────────────────────────────────

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Lifecycle Rules ──────────────────────────────────────────

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  # Move old versions to cheaper storage after 30 days,
  # delete after 90 days.
  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  # Clean up incomplete multipart uploads after 7 days
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Move infrequently accessed current objects to IA after 90 days
  rule {
    id     = "transition-infrequent"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }
}

# ── CORS (for direct browser uploads if needed) ─────────────

resource "aws_s3_bucket_cors_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = ["https://${var.domain_name}"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# ──────────────────────────────────────────────────────────────
# AWS WAFv2 — Edge-layer protection for ALB
# ──────────────────────────────────────────────────────────────
#
# Associates a WAFv2 Web ACL with the application load balancer
# using AWS Managed Rules for comprehensive protection against
# common web exploits, known bad inputs, and bot abuse.

resource "aws_wafv2_web_acl" "main" {
  name        = "${local.name_prefix}-waf"
  description = "WAF for ${local.name_prefix} ALB — managed rules + rate limiting"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # ── AWS Core Rule Set (CRS) ────────────────────────────────
  # Protects against OWASP Top 10 including XSS, SQLi, path traversal
  rule {
    name     = "aws-managed-common"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-common"
      sampled_requests_enabled   = true
    }
  }

  # ── Known Bad Inputs ───────────────────────────────────────
  # Blocks requests with known malicious patterns (Log4j, etc.)
  rule {
    name     = "aws-managed-known-bad-inputs"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # ── SQL Injection Protection ───────────────────────────────
  rule {
    name     = "aws-managed-sqli"
    priority = 30

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-sqli"
      sampled_requests_enabled   = true
    }
  }

  # ── Bot Control ────────────────────────────────────────────
  # Identifies and controls common and targeted bots
  rule {
    name     = "aws-managed-bot-control"
    priority = 40

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesBotControlRuleSet"

        managed_rule_group_configs {
          aws_managed_rules_bot_control_rule_set {
            inspection_level = "COMMON"
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-bot-control"
      sampled_requests_enabled   = true
    }
  }

  # ── IP Reputation ──────────────────────────────────────────
  # Blocks IPs from Amazon threat intelligence feeds
  rule {
    name     = "aws-managed-ip-reputation"
    priority = 50

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  # ── Rate Limiting ──────────────────────────────────────────
  # Global rate limit: 2000 requests per 5 minutes per IP
  rule {
    name     = "rate-limit-per-ip"
    priority = 60

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-waf"
    sampled_requests_enabled   = true
  }

  tags = { Name = "${local.name_prefix}-waf" }
}

# ── Associate WAF with ALB ───────────────────────────────────

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# ── CloudWatch logging for WAF ───────────────────────────────

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.main.arn

  logging_filter {
    default_behavior = "DROP"

    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ANY"

      condition {
        action_condition {
          action = "BLOCK"
        }
      }

      condition {
        action_condition {
          action = "COUNT"
        }
      }
    }
  }
}

resource "aws_cloudwatch_log_group" "waf" {
  # WAF logging requires the log group name to start with "aws-waf-logs-"
  name              = "aws-waf-logs-${local.name_prefix}"
  retention_in_days = 30

  tags = { Name = "${local.name_prefix}-waf-logs" }
}

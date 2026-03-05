"""Email sending abstraction with pluggable backends.

Supports SMTP, SendGrid, and AWS SES. Falls back gracefully when not configured.
All email delivery happens via Celery tasks to avoid blocking API requests.

Usage:
    from app.core.email import send_email, EmailTemplate

    await send_email(
        to="user@example.com",
        template=EmailTemplate.VERIFY_EMAIL,
        context={"verify_url": "https://..."},
    )
"""

import enum
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


class EmailTemplate(enum.StrEnum):
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"
    INVITATION = "invitation"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    WELCOME = "welcome"
    DATA_EXPORT_READY = "data_export_ready"
    SECURITY_ALERT = "security_alert"


# Template definitions: subject + body (plain text)
TEMPLATES: dict[str, dict[str, str]] = {
    EmailTemplate.VERIFY_EMAIL: {
        "subject": "Verify your email address",
        "body": (
            "Hello {display_name},\n\n"
            "Please verify your email address by clicking the link below:\n\n"
            "{verify_url}\n\n"
            "This link expires in 24 hours.\n\n"
            "If you didn't create an account, you can safely ignore this email."
        ),
    },
    EmailTemplate.PASSWORD_RESET: {
        "subject": "Reset your password",
        "body": (
            "Hello {display_name},\n\n"
            "We received a request to reset your password. Click the link below:\n\n"
            "{reset_url}\n\n"
            "This link expires in 1 hour.\n\n"
            "If you didn't request this, you can safely ignore this email."
        ),
    },
    EmailTemplate.INVITATION: {
        "subject": "You've been invited to join {tenant_name}",
        "body": (
            "Hello,\n\n"
            "{inviter_name} has invited you to join {tenant_name} as a {role}.\n\n"
            "Click the link below to accept:\n\n"
            "{invite_url}\n\n"
            "This invitation expires in 7 days."
        ),
    },
    EmailTemplate.JOB_COMPLETED: {
        "subject": "Job completed: {job_type}",
        "body": (
            "Your job {job_id} ({job_type}) has completed successfully.\n\n"
            "View results: {job_url}"
        ),
    },
    EmailTemplate.JOB_FAILED: {
        "subject": "Job failed: {job_type}",
        "body": (
            "Your job {job_id} ({job_type}) has failed.\n\n"
            "Error: {error}\n\n"
            "View details: {job_url}"
        ),
    },
    EmailTemplate.WELCOME: {
        "subject": "Welcome to {app_name}!",
        "body": (
            "Welcome {display_name}!\n\n"
            "Your account has been created. Get started by:\n\n"
            "1. Verifying your email: {verify_url}\n"
            "2. Creating your first API key\n"
            "3. Submitting your first job\n\n"
            "Documentation: {docs_url}"
        ),
    },
    EmailTemplate.DATA_EXPORT_READY: {
        "subject": "Your data export is ready",
        "body": (
            "Hello {display_name},\n\n"
            "Your data export is ready for download:\n\n"
            "{download_url}\n\n"
            "This link expires in 48 hours."
        ),
    },
    EmailTemplate.SECURITY_ALERT: {
        "subject": "Security alert: {alert_type}",
        "body": (
            "Hello {display_name},\n\n"
            "We detected a security event on your account:\n\n"
            "{alert_message}\n\n"
            "If this wasn't you, please secure your account immediately."
        ),
    },
}


def render_template(template: EmailTemplate, context: dict) -> tuple[str, str]:
    """Render an email template with the given context.

    Returns (subject, body) tuple.
    """
    tmpl = TEMPLATES.get(template)
    if not tmpl:
        raise ValueError(f"Unknown email template: {template}")

    subject = tmpl["subject"].format_map({**context, "app_name": settings.OTEL_SERVICE_NAME})
    body = tmpl["body"].format_map({**context, "app_name": settings.OTEL_SERVICE_NAME})
    return subject, body


class EmailSender:
    """Abstract email sender."""

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        raise NotImplementedError


class SMTPEmailSender(EmailSender):
    """Send emails via SMTP."""

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.EMAIL_FROM
            msg["To"] = to

            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                if settings.SMTP_USERNAME:
                    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("email_sent", to=to, subject=subject)
            return True
        except Exception:
            logger.error("email_send_failed", to=to, subject=subject, exc_info=True)
            return False


class LogEmailSender(EmailSender):
    """Log emails instead of sending (for development/testing)."""

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        logger.info("email_logged", to=to, subject=subject, body=body[:200])
        return True


def get_email_sender() -> EmailSender:
    """Get the configured email sender."""
    if settings.SMTP_HOST:
        return SMTPEmailSender()
    return LogEmailSender()


def send_email_sync(to: str, template: EmailTemplate, context: dict) -> bool:
    """Send an email synchronously (for use in Celery tasks)."""
    subject, body = render_template(template, context)
    sender = get_email_sender()
    return sender.send(to, subject, body)

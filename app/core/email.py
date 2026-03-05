"""Email sending via Brevo (formerly Sendinblue) transactional API.

Uses httpx to call the Brevo REST API for reliable transactional email delivery.
Falls back to logging when BREVO_API_KEY is not configured (development mode).

Usage:
    from app.core.email import send_email, EmailTemplate

    await send_email(
        to="user@example.com",
        template=EmailTemplate.VERIFY_EMAIL,
        context={"verify_url": "https://..."},
    )
"""

import enum

import httpx
import structlog

from app.config import settings
from app.core.circuit_breaker import email_breaker

logger = structlog.stdlib.get_logger()

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


class EmailTemplate(enum.StrEnum):
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"
    INVITATION = "invitation"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    WELCOME = "welcome"
    DATA_EXPORT_READY = "data_export_ready"
    SECURITY_ALERT = "security_alert"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_CANCELED = "subscription_canceled"


# Template definitions: subject + plain text body + HTML body
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>Verify your email</h2>"
            "<p>Hello {display_name},</p>"
            "<p>Please verify your email address by clicking the button below:</p>"
            '<a href="{verify_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Verify Email</a>'
            "<p style=\"margin-top:24px;color:#6b7280;font-size:14px\">"
            "This link expires in 24 hours. If you didn't create an account, "
            "you can safely ignore this email.</p></div>"
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>Reset your password</h2>"
            "<p>Hello {display_name},</p>"
            "<p>We received a request to reset your password:</p>"
            '<a href="{reset_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Reset Password</a>'
            "<p style=\"margin-top:24px;color:#6b7280;font-size:14px\">"
            "This link expires in 1 hour. If you didn't request this, "
            "ignore this email.</p></div>"
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>You're invited!</h2>"
            "<p><strong>{inviter_name}</strong> has invited you to join "
            "<strong>{tenant_name}</strong> as a <strong>{role}</strong>.</p>"
            '<a href="{invite_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Accept Invitation</a>'
            '<p style="margin-top:24px;color:#6b7280;font-size:14px">'
            "This invitation expires in 7 days.</p></div>"
        ),
    },
    EmailTemplate.JOB_COMPLETED: {
        "subject": "Job completed: {job_type}",
        "body": (
            "Your job {job_id} ({job_type}) has completed successfully.\n\n"
            "View results: {job_url}"
        ),
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            '<h2 style="color:#16a34a">Job Completed</h2>'
            "<p>Your job <strong>{job_id}</strong> ({job_type}) has completed.</p>"
            '<a href="{job_url}" style="display:inline-block;padding:12px 24px;'
            'background:#16a34a;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">View Results</a></div>'
        ),
    },
    EmailTemplate.JOB_FAILED: {
        "subject": "Job failed: {job_type}",
        "body": (
            "Your job {job_id} ({job_type}) has failed.\n\n"
            "Error: {error}\n\n"
            "View details: {job_url}"
        ),
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            '<h2 style="color:#dc2626">Job Failed</h2>'
            "<p>Your job <strong>{job_id}</strong> ({job_type}) has failed.</p>"
            '<p style="background:#fef2f2;padding:12px;border-radius:6px;'
            'color:#991b1b">Error: {error}</p>'
            '<a href="{job_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">View Details</a></div>'
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>Welcome to {app_name}!</h2>"
            "<p>Hello {display_name},</p>"
            "<p>Your account has been created. Get started:</p>"
            '<ol><li><a href="{verify_url}">Verify your email</a></li>'
            "<li>Create your first API key</li>"
            "<li>Submit your first job</li></ol>"
            '<p><a href="{docs_url}">Read the documentation</a></p></div>'
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>Data Export Ready</h2>"
            "<p>Hello {display_name},</p>"
            "<p>Your data export is ready for download:</p>"
            '<a href="{download_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Download Export</a>'
            '<p style="margin-top:24px;color:#6b7280;font-size:14px">'
            "This link expires in 48 hours.</p></div>"
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
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            '<h2 style="color:#dc2626">Security Alert</h2>'
            "<p>Hello {display_name},</p>"
            "<p>We detected a security event on your account:</p>"
            '<p style="background:#fef2f2;padding:12px;border-radius:6px;'
            'color:#991b1b">{alert_message}</p>'
            "<p>If this wasn't you, please secure your account immediately.</p></div>"
        ),
    },
    EmailTemplate.PAYMENT_RECEIVED: {
        "subject": "Payment received — thank you!",
        "body": (
            "Hello {display_name},\n\n"
            "We've received your payment of {amount} for {plan_name}.\n\n"
            "Thank you for your continued support."
        ),
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            '<h2 style="color:#16a34a">Payment Received</h2>'
            "<p>Hello {display_name},</p>"
            "<p>We've received your payment of <strong>{amount}</strong> "
            "for <strong>{plan_name}</strong>.</p>"
            "<p>Thank you for your continued support.</p></div>"
        ),
    },
    EmailTemplate.PAYMENT_FAILED: {
        "subject": "Payment failed — action required",
        "body": (
            "Hello {display_name},\n\n"
            "We were unable to process your payment for {plan_name}.\n\n"
            "Please update your payment method to avoid service interruption:\n\n"
            "{billing_url}"
        ),
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            '<h2 style="color:#dc2626">Payment Failed</h2>'
            "<p>Hello {display_name},</p>"
            "<p>We were unable to process your payment for "
            "<strong>{plan_name}</strong>.</p>"
            "<p>Please update your payment method to avoid service interruption:</p>"
            '<a href="{billing_url}" style="display:inline-block;padding:12px 24px;'
            'background:#dc2626;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Update Payment Method</a></div>'
        ),
    },
    EmailTemplate.SUBSCRIPTION_CANCELED: {
        "subject": "Subscription canceled",
        "body": (
            "Hello {display_name},\n\n"
            "Your {plan_name} subscription has been canceled.\n\n"
            "You can continue using the service until the end of your billing period.\n\n"
            "We'd love to have you back: {billing_url}"
        ),
        "html": (
            '<div style="font-family:sans-serif;max-width:600px;margin:0 auto">'
            "<h2>Subscription Canceled</h2>"
            "<p>Hello {display_name},</p>"
            "<p>Your <strong>{plan_name}</strong> subscription has been canceled.</p>"
            "<p>You can continue using the service until the end of your "
            "billing period.</p>"
            '<a href="{billing_url}" style="display:inline-block;padding:12px 24px;'
            'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;'
            'font-weight:600">Resubscribe</a></div>'
        ),
    },
}


def render_template(template: EmailTemplate, context: dict) -> tuple[str, str, str]:
    """Render an email template with the given context.

    Returns (subject, text_body, html_body) tuple.
    """
    tmpl = TEMPLATES.get(template)
    if not tmpl:
        raise ValueError(f"Unknown email template: {template}")

    ctx = {**context, "app_name": settings.OTEL_SERVICE_NAME}
    subject = tmpl["subject"].format_map(ctx)
    body = tmpl["body"].format_map(ctx)
    html = tmpl["html"].format_map(ctx)
    return subject, body, html


class EmailSender:
    """Abstract email sender."""

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        raise NotImplementedError

    def send_sync(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        raise NotImplementedError


class BrevoEmailSender(EmailSender):
    """Send emails via Brevo (Sendinblue) transactional API."""

    def _build_payload(self, to: str, subject: str, body: str, html: str | None = None) -> dict:
        payload: dict = {
            "sender": {
                "name": settings.BREVO_SENDER_NAME,
                "email": settings.BREVO_SENDER_EMAIL,
            },
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        }
        if html:
            payload["htmlContent"] = html
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        if email_breaker.is_open("brevo"):
            logger.warning("email_circuit_open", to=to, subject=subject)
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    BREVO_API_URL,
                    json=self._build_payload(to, subject, body, html),
                    headers=self._headers(),
                )
                resp.raise_for_status()

            email_breaker.record_success("brevo")
            logger.info("email_sent", to=to, subject=subject, provider="brevo")
            return True
        except Exception:
            email_breaker.record_failure("brevo")
            logger.error("email_send_failed", to=to, subject=subject, provider="brevo", exc_info=True)
            return False

    def send_sync(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        """Synchronous send for Celery tasks."""
        if email_breaker.is_open("brevo"):
            logger.warning("email_circuit_open", to=to, subject=subject)
            return False

        try:
            resp = httpx.post(
                BREVO_API_URL,
                json=self._build_payload(to, subject, body, html),
                headers=self._headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            email_breaker.record_success("brevo")
            logger.info("email_sent", to=to, subject=subject, provider="brevo")
            return True
        except Exception:
            email_breaker.record_failure("brevo")
            logger.error("email_send_failed", to=to, subject=subject, provider="brevo", exc_info=True)
            return False


class LogEmailSender(EmailSender):
    """Log emails instead of sending (for development/testing)."""

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        logger.info("email_logged", to=to, subject=subject, body=body[:200])
        return True

    def send_sync(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        logger.info("email_logged", to=to, subject=subject, body=body[:200])
        return True


def get_email_sender() -> EmailSender:
    """Get the configured email sender."""
    if settings.email_configured:
        return BrevoEmailSender()
    return LogEmailSender()


async def send_email(to: str, template: EmailTemplate, context: dict) -> bool:
    """Send an email asynchronously using the configured provider."""
    subject, body, html = render_template(template, context)
    sender = get_email_sender()
    return await sender.send(to, subject, body, html)


def send_email_sync(to: str, template: EmailTemplate, context: dict) -> bool:
    """Send an email synchronously (for use in Celery tasks)."""
    subject, body, html = render_template(template, context)
    sender = get_email_sender()
    return sender.send_sync(to, subject, body, html)

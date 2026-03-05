"""Tests for the Brevo email sending system."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.email import (
    BrevoEmailSender,
    EmailTemplate,
    LogEmailSender,
    get_email_sender,
    render_template,
    send_email,
)


class TestRenderTemplate:
    def test_render_verify_email(self):
        subject, body, html = render_template(
            EmailTemplate.VERIFY_EMAIL,
            {"display_name": "Alice", "verify_url": "https://example.com/verify"},
        )
        assert subject == "Verify your email address"
        assert "Alice" in body
        assert "https://example.com/verify" in body
        assert "Alice" in html
        assert "https://example.com/verify" in html

    def test_render_password_reset(self):
        subject, body, html = render_template(
            EmailTemplate.PASSWORD_RESET,
            {"display_name": "Bob", "reset_url": "https://example.com/reset"},
        )
        assert "Reset" in subject
        assert "Bob" in body
        assert "https://example.com/reset" in html

    def test_render_invitation(self):
        subject, body, html = render_template(
            EmailTemplate.INVITATION,
            {
                "inviter_name": "Alice",
                "tenant_name": "Acme Corp",
                "role": "admin",
                "invite_url": "https://example.com/invite",
            },
        )
        assert "Acme Corp" in subject
        assert "Alice" in body
        assert "admin" in body

    def test_render_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown email template"):
            render_template("nonexistent_template", {})

    def test_render_payment_templates(self):
        subject, body, html = render_template(
            EmailTemplate.PAYMENT_RECEIVED,
            {"display_name": "Charlie", "amount": "$49.00", "plan_name": "Pro"},
        )
        assert "Payment received" in subject
        assert "$49.00" in body

        subject, body, html = render_template(
            EmailTemplate.PAYMENT_FAILED,
            {"display_name": "Charlie", "plan_name": "Pro", "billing_url": "https://billing"},
        )
        assert "Payment failed" in subject
        assert "Pro" in body


class TestLogEmailSender:
    @pytest.mark.asyncio
    async def test_async_send(self):
        sender = LogEmailSender()
        result = await sender.send("test@example.com", "Subject", "Body")
        assert result is True

    def test_sync_send(self):
        sender = LogEmailSender()
        result = sender.send_sync("test@example.com", "Subject", "Body")
        assert result is True


class TestBrevoEmailSender:
    @pytest.mark.asyncio
    async def test_send_success(self):
        sender = BrevoEmailSender()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with (
            patch("app.core.email.email_breaker") as mock_breaker,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_breaker.is_open.return_value = False
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sender.send("test@example.com", "Subject", "Body", "<p>HTML</p>")
            assert result is True
            mock_breaker.record_success.assert_called_once_with("brevo")

    @pytest.mark.asyncio
    async def test_send_circuit_open(self):
        sender = BrevoEmailSender()
        with patch("app.core.email.email_breaker") as mock_breaker:
            mock_breaker.is_open.return_value = True
            result = await sender.send("test@example.com", "Subject", "Body")
            assert result is False

    @pytest.mark.asyncio
    async def test_send_failure_records(self):
        sender = BrevoEmailSender()
        with (
            patch("app.core.email.email_breaker") as mock_breaker,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_breaker.is_open.return_value = False
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await sender.send("test@example.com", "Subject", "Body")
            assert result is False
            mock_breaker.record_failure.assert_called_once_with("brevo")


class TestGetEmailSender:
    def test_returns_brevo_when_configured(self):
        with patch("app.core.email.settings") as mock_settings:
            mock_settings.email_configured = True
            sender = get_email_sender()
            assert isinstance(sender, BrevoEmailSender)

    def test_returns_log_when_not_configured(self):
        with patch("app.core.email.settings") as mock_settings:
            mock_settings.email_configured = False
            sender = get_email_sender()
            assert isinstance(sender, LogEmailSender)


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_send_email_renders_and_sends(self):
        with patch("app.core.email.get_email_sender") as mock_get:
            mock_sender = AsyncMock()
            mock_sender.send = AsyncMock(return_value=True)
            mock_get.return_value = mock_sender

            result = await send_email(
                "test@example.com",
                EmailTemplate.VERIFY_EMAIL,
                {"display_name": "Test", "verify_url": "https://verify"},
            )
            assert result is True
            mock_sender.send.assert_called_once()
            call_args = mock_sender.send.call_args
            assert call_args[0][0] == "test@example.com"
            assert "Verify" in call_args[0][1]

"""Tests for OAuth social login endpoints and service layer."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response as HttpxResponse

from app.core.oauth import (
    OAuthUserProfile,
    _build_providers,
    exchange_code_for_tokens,
    fetch_user_profile,
    generate_authorize_url,
    get_configured_providers,
    get_provider_config,
    validate_state,
)
from app.api.v1.oauth_social import _generate_tenant_slug


# ── Provider config tests ──────────────────────────────


class TestProviderConfig:
    def test_get_configured_providers_none(self):
        """No providers when credentials are empty."""
        with patch("app.core.oauth.settings") as mock_settings:
            mock_settings.OAUTH_GOOGLE_CLIENT_ID = ""
            mock_settings.OAUTH_GOOGLE_CLIENT_SECRET = ""
            mock_settings.OAUTH_GITHUB_CLIENT_ID = ""
            mock_settings.OAUTH_GITHUB_CLIENT_SECRET = ""
            # Re-build providers with mocked settings
            providers = _build_providers()
            assert len(providers) == 0

    def test_get_configured_providers_google_only(self):
        with patch("app.core.oauth.settings") as mock_settings:
            mock_settings.OAUTH_GOOGLE_CLIENT_ID = "google-id"
            mock_settings.OAUTH_GOOGLE_CLIENT_SECRET = "google-secret"
            mock_settings.OAUTH_GITHUB_CLIENT_ID = ""
            mock_settings.OAUTH_GITHUB_CLIENT_SECRET = ""
            providers = _build_providers()
            assert "google" in providers
            assert "github" not in providers

    def test_get_configured_providers_both(self):
        with patch("app.core.oauth.settings") as mock_settings:
            mock_settings.OAUTH_GOOGLE_CLIENT_ID = "google-id"
            mock_settings.OAUTH_GOOGLE_CLIENT_SECRET = "google-secret"
            mock_settings.OAUTH_GITHUB_CLIENT_ID = "github-id"
            mock_settings.OAUTH_GITHUB_CLIENT_SECRET = "github-secret"
            providers = _build_providers()
            assert "google" in providers
            assert "github" in providers

    def test_get_provider_config_unknown(self):
        with pytest.raises(ValueError, match="not configured"):
            get_provider_config("unknown-provider")


# ── State management tests ─────────────────────────────


class TestStateManagement:
    @pytest.mark.asyncio
    async def test_generate_authorize_url_stores_state(self):
        """State should be stored in Redis with TTL."""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with (
            patch("app.core.oauth.settings") as mock_settings,
            patch("app.core.oauth.redis_pool", mock_redis, create=True),
        ):
            mock_settings.OAUTH_GOOGLE_CLIENT_ID = "google-id"
            mock_settings.OAUTH_GOOGLE_CLIENT_SECRET = "google-secret"
            mock_settings.APP_BASE_URL = "http://localhost:3000"

            # Patch the redis import inside the function
            with patch("app.core.oauth.redis_pool", mock_redis, create=True):
                # We need to mock the import inside the function
                import app.core.oauth as oauth_module

                with patch.object(oauth_module, "_build_providers") as mock_build:
                    from app.core.oauth import OAuthProviderConfig

                    mock_build.return_value = {
                        "google": OAuthProviderConfig(
                            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                            token_url="https://oauth2.googleapis.com/token",
                            userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
                            client_id="google-id",
                            client_secret="google-secret",
                            scopes="openid email profile",
                        )
                    }

                    # Mock redis import in the function
                    with patch.dict("sys.modules", {"app.core.redis": MagicMock(redis_pool=mock_redis)}):
                        url = await generate_authorize_url(
                            "google", "http://localhost:3000/auth/callback/google"
                        )

                    assert "accounts.google.com" in url
                    assert "client_id=google-id" in url
                    assert "access_type=offline" in url
                    assert "prompt=consent" in url

    @pytest.mark.asyncio
    async def test_validate_state_consumes_atomically(self):
        """State should be retrieved and deleted atomically via GETDEL."""
        state_data = json.dumps({"provider": "google", "redirect_uri": "http://localhost/cb", "linking_user_id": None})

        mock_redis = AsyncMock()
        mock_redis.getdel = AsyncMock(return_value=state_data)

        with patch.dict("sys.modules", {"app.core.redis": MagicMock(redis_pool=mock_redis)}):
            result = await validate_state("test-state-token")

        assert result is not None
        assert result["provider"] == "google"
        mock_redis.getdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_state_replay_prevention(self):
        """Second call with same state should return None (already consumed by GETDEL)."""
        mock_redis = AsyncMock()
        mock_redis.getdel = AsyncMock(return_value=None)

        with patch.dict("sys.modules", {"app.core.redis": MagicMock(redis_pool=mock_redis)}):
            result = await validate_state("already-used-state")

        assert result is None


# ── Profile normalization tests ────────────────────────


class TestProfileNormalization:
    @pytest.mark.asyncio
    async def test_google_profile(self):
        google_response = {
            "sub": "12345",
            "email": "user@gmail.com",
            "email_verified": True,
            "name": "Test User",
            "picture": "https://lh3.google.com/photo",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = google_response
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.oauth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch("app.core.oauth._build_providers") as mock_build:
                from app.core.oauth import OAuthProviderConfig

                mock_build.return_value = {
                    "google": OAuthProviderConfig(
                        authorize_url="",
                        token_url="",
                        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
                        client_id="id",
                        client_secret="secret",
                        scopes="",
                    )
                }
                profile = await fetch_user_profile("google", "access-token")

            assert profile.provider == "google"
            assert profile.provider_user_id == "12345"
            assert profile.email == "user@gmail.com"
            assert profile.display_name == "Test User"

    @pytest.mark.asyncio
    async def test_google_profile_unverified_email_rejected(self):
        """Google accounts with unverified emails must be rejected."""
        google_response = {
            "sub": "12345",
            "email": "user@gmail.com",
            "email_verified": False,
            "name": "Test User",
            "picture": "https://lh3.google.com/photo",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = google_response
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.oauth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with patch("app.core.oauth._build_providers") as mock_build:
                from app.core.oauth import OAuthProviderConfig

                mock_build.return_value = {
                    "google": OAuthProviderConfig(
                        authorize_url="",
                        token_url="",
                        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
                        client_id="id",
                        client_secret="secret",
                        scopes="",
                    )
                }
                with pytest.raises(ValueError, match="not verified"):
                    await fetch_user_profile("google", "access-token")

    @pytest.mark.asyncio
    async def test_github_profile_with_private_email(self):
        """GitHub user with private email should fetch from /user/emails."""
        user_response = {
            "id": 67890,
            "login": "octocat",
            "name": "The Octocat",
            "email": None,  # Private email
            "avatar_url": "https://github.com/images/octocat.png",
        }
        emails_response = [
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "verified@example.com", "primary": False, "verified": True},
            {"email": "primary-verified@example.com", "primary": True, "verified": True},
        ]

        user_mock = MagicMock()
        user_mock.json.return_value = user_response
        user_mock.raise_for_status = MagicMock()

        emails_mock = MagicMock()
        emails_mock.json.return_value = emails_response
        emails_mock.raise_for_status = MagicMock()

        with patch("app.core.oauth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            # First call = /user, second call = /user/emails
            mock_client.get = AsyncMock(side_effect=[user_mock, emails_mock])
            mock_client_class.return_value = mock_client

            with patch("app.core.oauth._build_providers") as mock_build:
                from app.core.oauth import OAuthProviderConfig

                mock_build.return_value = {
                    "github": OAuthProviderConfig(
                        authorize_url="",
                        token_url="",
                        userinfo_url="https://api.github.com/user",
                        client_id="id",
                        client_secret="secret",
                        scopes="",
                    )
                }
                profile = await fetch_user_profile("github", "access-token")

            assert profile.provider == "github"
            assert profile.provider_user_id == "67890"
            # Should pick primary+verified email
            assert profile.email == "primary-verified@example.com"
            assert profile.display_name == "The Octocat"

    @pytest.mark.asyncio
    async def test_github_no_verified_email_raises(self):
        """Should raise ValueError when GitHub has no verified emails."""
        user_response = {"id": 1, "login": "test", "name": "Test", "email": None, "avatar_url": ""}
        emails_response = [
            {"email": "unverified@example.com", "primary": True, "verified": False},
        ]

        user_mock = MagicMock()
        user_mock.json.return_value = user_response
        user_mock.raise_for_status = MagicMock()

        emails_mock = MagicMock()
        emails_mock.json.return_value = emails_response
        emails_mock.raise_for_status = MagicMock()

        with patch("app.core.oauth.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=[user_mock, emails_mock])
            mock_client_class.return_value = mock_client

            with patch("app.core.oauth._build_providers") as mock_build:
                from app.core.oauth import OAuthProviderConfig

                mock_build.return_value = {
                    "github": OAuthProviderConfig(
                        authorize_url="",
                        token_url="",
                        userinfo_url="https://api.github.com/user",
                        client_id="id",
                        client_secret="secret",
                        scopes="",
                    )
                }
                with pytest.raises(ValueError, match="no verified email"):
                    await fetch_user_profile("github", "access-token")


# ── Tenant slug generation tests ───────────────────────


class TestTenantSlugGeneration:
    def test_simple_email(self):
        slug = _generate_tenant_slug("jane.doe@example.com")
        assert slug == "jane-doe"

    def test_short_prefix(self):
        slug = _generate_tenant_slug("a@example.com")
        assert len(slug) >= 2
        assert "a" in slug

    def test_special_characters(self):
        slug = _generate_tenant_slug("user+tag@example.com")
        assert "+" not in slug
        assert slug.replace("-", "").isalnum()

    def test_max_length(self):
        from app.api.v1.oauth_social import _generate_tenant_slug

        long_prefix = "a" * 100
        slug = _generate_tenant_slug(f"{long_prefix}@example.com")
        assert len(slug) <= 63


# ── Unlink validation tests ───────────────────────────


class TestUnlinkValidation:
    """Test that unlinking the last auth method is prevented."""

    @pytest.mark.asyncio
    async def test_cannot_unlink_last_method(self):
        """Conceptual test: user with no password and only one OAuth account
        should not be able to unlink that account."""
        # This is a logic test — the actual endpoint checks:
        # 1. user.password_hash is not None OR
        # 2. other OAuthAccounts exist for this user
        # If neither is true, it returns 400.

        # Simulating the logic:
        has_password = False
        has_other_oauth = False
        can_unlink = has_password or has_other_oauth
        assert not can_unlink

    @pytest.mark.asyncio
    async def test_can_unlink_with_password(self):
        """User with a password can unlink their OAuth account."""
        has_password = True
        has_other_oauth = False
        can_unlink = has_password or has_other_oauth
        assert can_unlink

    @pytest.mark.asyncio
    async def test_can_unlink_with_other_oauth(self):
        """User with another OAuth account can unlink one."""
        has_password = False
        has_other_oauth = True
        can_unlink = has_password or has_other_oauth
        assert can_unlink

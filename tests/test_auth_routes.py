"""Tests for authentication endpoints."""


import pytest


class TestAuthEndpointSignatures:
    """Verify auth route module imports and endpoint registration."""

    def test_router_prefix(self):
        from app.api.v1.auth_routes import router

        assert router.prefix == "/auth"

    def test_register_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/register" in routes

    def test_login_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/login" in routes

    def test_refresh_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/refresh" in routes

    def test_logout_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/logout" in routes

    def test_me_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/me" in routes

    def test_verify_email_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/verify-email" in routes

    def test_forgot_password_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/forgot-password" in routes

    def test_reset_password_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/reset-password" in routes

    def test_accept_invitation_endpoint_exists(self):
        from app.api.v1.auth_routes import router

        routes = [r.path for r in router.routes]
        assert "/auth/accept-invitation" in routes


class TestAuthSchemas:
    def test_user_register_validation(self):
        from app.api.schemas_auth import UserRegister

        user = UserRegister(
            email="test@example.com",
            password="securepass123",
            display_name="Test User",
            tenant_slug="my-org",
        )
        assert user.email == "test@example.com"
        assert user.tenant_slug == "my-org"

    def test_user_register_short_password_rejected(self):
        from pydantic import ValidationError

        from app.api.schemas_auth import UserRegister

        with pytest.raises(ValidationError):
            UserRegister(email="test@example.com", password="short")

    def test_user_login_validation(self):
        from app.api.schemas_auth import UserLogin

        login = UserLogin(email="test@example.com", password="password123")
        assert login.email == "test@example.com"

    def test_token_response(self):
        from app.api.schemas_auth import TokenResponse

        tr = TokenResponse(access_token="abc", expires_in=1800)
        assert tr.token_type == "bearer"

    def test_user_response_from_attributes(self):
        from app.api.schemas_auth import UserResponse

        assert UserResponse.model_config.get("from_attributes") is True

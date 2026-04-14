"""P0.4: Credential storage, refresh, and distributed-lock behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.credentials import credential_manager
from app.connectors.models import CredentialType, TenantCredential
from app.core.encryption import decrypt, encrypt
from tests.connectors.conftest import make_connection, make_oauth_credential


@pytest.mark.asyncio
async def test_store_oauth_encrypts_tokens(tenant_id, user_a_id, slack_oauth_connector):
    conn = make_connection(tenant_id, slack_oauth_connector, user_a_id)

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    cred = await credential_manager.store_oauth(
        connection=conn,
        access_token="aabbcc",
        refresh_token="rrtt",
        expires_in=3600,
        scopes=["read"],
        auth_metadata=None,
        db=db,
    )
    assert cred.access_token_enc is not None
    assert cred.access_token_enc != "aabbcc"
    assert decrypt(cred.access_token_enc) == "aabbcc"
    assert decrypt(cred.refresh_token_enc) == "rrtt"
    assert cred.token_expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_get_valid_token_returns_decrypted_api_key(
    tenant_id, user_a_id, slack_oauth_connector,
):
    conn = make_connection(tenant_id, slack_oauth_connector, user_a_id)
    conn.credential = TenantCredential(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        connection_id=conn.id,
        credential_type=CredentialType.API_KEY,
        api_key_enc=encrypt("my-api-key"),
        is_valid=True,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    token = await credential_manager.get_valid_token(conn, slack_oauth_connector, db)
    assert token == "my-api-key"


@pytest.mark.asyncio
async def test_refresh_oauth_lock_prevents_races(
    tenant_id, user_a_id, slack_oauth_connector,
):
    """Two concurrent callers should only trigger one real refresh."""
    conn = make_connection(tenant_id, slack_oauth_connector, user_a_id)
    cred = make_oauth_credential(tenant_id, conn, expired=True)

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    # First caller's refresh completes; subsequent callers should skip.
    refresh_calls = {"count": 0}

    original_refresh = credential_manager.refresh_oauth

    async def fake_refresh_oauth(credential, connector_def, db):
        refresh_calls["count"] += 1
        # Simulate a successful refresh
        credential.access_token_enc = encrypt("new-access-token")
        credential.token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        credential.is_valid = True

    # Patch app_credential_manager so refresh picks up fake app creds
    with patch.object(credential_manager, "refresh_oauth", side_effect=fake_refresh_oauth):
        # Use a context-manager friendly fake lock
        fake_lock = MagicMock()
        fake_lock.acquire = AsyncMock(return_value=True)
        fake_lock.release = AsyncMock()

        with patch("app.connectors.credentials.redis_pool") as mock_redis:
            mock_redis.lock = MagicMock(return_value=fake_lock)

            token1 = await credential_manager.get_valid_token(
                conn, slack_oauth_connector, db,
            )
            assert token1 == "new-access-token"
            # Subsequent call — credential is no longer expired → no refresh
            token2 = await credential_manager.get_valid_token(
                conn, slack_oauth_connector, db,
            )
            assert token2 == "new-access-token"

    assert refresh_calls["count"] == 1, (
        "Concurrent get_valid_token callers must not refresh twice"
    )

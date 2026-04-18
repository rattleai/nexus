"""Signed MCP server registry verification (P1.3).

Three-tier trust model:

* **VERIFIED** — server card at ``/.well-known/mcp`` carries a valid Ed25519
  signature from the platform's registry public key (or a trusted co-signer),
  AND the server appears on the official MCP registry's allow-list.
* **TRUSTED** — signature OK but not on the allow-list, OR admin-approved
  per-tenant without signature. Descriptions are passed through but the
  connector is flagged in the UI.
* **UNTRUSTED** — anything else. Blocked in production unless
  ``CONNECTOR_REGISTRY_ALLOW_UNTRUSTED`` is True (dev-only).

CVE-2025-6514 (mcp-remote RCE via malicious authorization_endpoint) is the
canonical example of why this gate exists — we must not let a tenant
register an arbitrary URL without a signed proof of identity.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from app.config import settings
from app.connectors.models import TrustLevel
from app.core.url_validation import validate_url

logger = structlog.stdlib.get_logger()


class RegistryVerificationError(Exception):
    """Raised when MCP server registry verification fails."""


@dataclass(frozen=True)
class ServerCard:
    """The ``/.well-known/mcp`` server card — minimal fields we care about."""

    name: str
    version: str
    description: str
    publisher: str | None
    signature: str | None
    signed_payload: str | None
    canonical_url: str | None


async def verify_mcp_server(url: str) -> TrustLevel:
    """Verify an MCP server URL and return its trust level.

    1. Validate URL (SSRF guard).
    2. Attempt to fetch ``<url>/.well-known/mcp``.
    3. If present, verify Ed25519 signature against the platform key.
    4. Cross-check against the official registry allow-list if configured.

    Raises ``RegistryVerificationError`` in production when the result would
    be ``UNTRUSTED`` and untrusted servers are not permitted.
    """
    validate_url(url)

    card = await _fetch_server_card(url)
    if card is None:
        return _gate_untrusted(
            url, reason="No /.well-known/mcp server card found",
        )

    if card.signature and card.signed_payload:
        if _verify_signature(card.signed_payload, card.signature):
            logger.info(
                "mcp_server_signature_verified",
                url=url,
                publisher=card.publisher,
            )
            if await _is_on_allow_list(url, card):
                return TrustLevel.VERIFIED
            return TrustLevel.TRUSTED
        else:
            return _gate_untrusted(
                url, reason="Invalid signature on server card",
            )

    # No signature provided → untrusted by default.
    return _gate_untrusted(url, reason="Server card is unsigned")


async def _fetch_server_card(url: str) -> ServerCard | None:
    """Fetch ``<url>/.well-known/mcp``. Returns None if absent or invalid."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    card_url = urljoin(base, "/.well-known/mcp")

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(card_url)
        if resp.status_code != 200:
            logger.debug(
                "mcp_server_card_not_found",
                url=card_url,
                status=resp.status_code,
            )
            return None
        data = resp.json()
    except Exception as exc:
        logger.debug(
            "mcp_server_card_fetch_failed",
            url=card_url,
            error=str(exc)[:200],
        )
        return None

    if not isinstance(data, dict):
        return None

    return ServerCard(
        name=str(data.get("name", "")),
        version=str(data.get("version", "")),
        description=str(data.get("description", "")),
        publisher=data.get("publisher"),
        signature=data.get("signature"),
        signed_payload=data.get("signed_payload"),
        canonical_url=data.get("canonical_url"),
    )


def _verify_signature(signed_payload: str, signature: str) -> bool:
    """Verify a base64-encoded Ed25519 signature over signed_payload.

    The platform's registry public key is loaded from
    ``settings.CONNECTOR_REGISTRY_PUBLIC_KEY_PATH``. If no key is configured,
    signatures cannot be verified and the function returns False.
    """
    key_path = settings.CONNECTOR_REGISTRY_PUBLIC_KEY_PATH
    if not key_path:
        logger.debug("mcp_registry_public_key_not_configured")
        return False

    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        logger.warning("cryptography_not_available_for_signature_verification")
        return False

    try:
        with open(key_path, "rb") as f:
            public_key = load_pem_public_key(f.read())
    except Exception as exc:
        logger.error(
            "mcp_registry_public_key_load_failed",
            path=key_path,
            error=str(exc)[:200],
        )
        return False

    if not isinstance(public_key, Ed25519PublicKey):
        logger.warning(
            "mcp_registry_public_key_wrong_type",
            expected="Ed25519PublicKey",
            got=type(public_key).__name__,
        )
        return False

    try:
        sig_bytes = base64.b64decode(signature)
        payload_bytes = signed_payload.encode()
        public_key.verify(sig_bytes, payload_bytes)
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        logger.warning(
            "mcp_signature_verify_error",
            error=str(exc)[:200],
        )
        return False


async def _is_on_allow_list(url: str, card: ServerCard) -> bool:
    """Check the official MCP registry (registry.modelcontextprotocol.io).

    Returns True if the server's canonical URL is present on the official
    allow-list. Absence from the registry does NOT mean the server is
    malicious — just that it hasn't been published.
    """
    registry_url = getattr(settings, "CONNECTOR_REGISTRY_URL", "")
    if not registry_url:
        return False

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{registry_url.rstrip('/')}/search",
                params={"canonical_url": card.canonical_url or url},
            )
        if resp.status_code != 200:
            return False
        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else []
        return len(items) > 0
    except Exception:
        logger.debug("mcp_registry_lookup_failed", exc_info=True)
        return False


def _gate_untrusted(url: str, *, reason: str) -> TrustLevel:
    """Either return UNTRUSTED or raise, depending on deployment mode."""
    if settings.DEBUG or getattr(settings, "CONNECTOR_REGISTRY_ALLOW_UNTRUSTED", False):
        logger.warning(
            "mcp_server_untrusted_allowed",
            url=url,
            reason=reason,
        )
        return TrustLevel.UNTRUSTED
    raise RegistryVerificationError(
        f"MCP server at {url} cannot be registered: {reason}. "
        f"In production, only signed/verified servers are allowed. "
        f"Enable CONNECTOR_REGISTRY_ALLOW_UNTRUSTED to bypass (dev only)."
    )

"""Agent-to-Agent communication security layer.

Provides:
    - Message signing: HMAC-SHA256 per message using ephemeral keys
    - Message integrity: Hash verification before processing
    - Replay protection: Monotonic sequence numbers per sender+recipient pair
    - Encrypted channels: Optional AES-256-GCM for sensitive inter-agent data
    - Cross-agent injection defense: Prompt firewall on message content

Integrates with:
    - app/agents/a2a.py for message send/receive
    - app/agents/capabilities.py for key derivation from capability tokens
    - app/ai/prompt_firewall.py for cross-agent injection scanning
    - app/core/encryption.py for AES-256-GCM envelope encryption
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis keys for sequence number tracking (replay protection)
_SEQ_KEY = "agent:a2a:seq:{tenant_id}:{from_id}:{to_id}"

# Maximum acceptable clock skew for message freshness (seconds)
_MAX_CLOCK_SKEW_SECONDS = 300  # 5 minutes


@dataclass
class SecureMessage:
    """A signed and optionally encrypted A2A message."""

    id: str = ""
    from_instance: str = ""
    to_instance: str = ""
    message_type: str = "request"
    content: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    timestamp: float = 0.0
    # Security fields
    message_hash: str = ""
    signature: str = ""
    sequence_number: int = 0
    encrypted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id or uuid.uuid4().hex,
            "from_instance": self.from_instance,
            "to_instance": self.to_instance,
            "message_type": self.message_type,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp or time.time(),
            "message_hash": self.message_hash,
            "signature": self.signature,
            "sequence_number": self.sequence_number,
            "encrypted": self.encrypted,
        }


class A2ASecurityLayer:
    """Security layer wrapping A2A communication.

    Usage:
        security = A2ASecurityLayer(tenant_id=...)
        # Sending:
        secure_msg = await security.sign_message(message, signing_key)
        # Receiving:
        verified = await security.verify_message(secure_msg, signing_key)
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def derive_signing_key(self, instance_id: str) -> bytes:
        """Derive a per-instance ephemeral signing key.

        Uses HMAC with the platform secret and instance ID for domain separation.
        """
        source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
        return hmac.new(
            source.encode(),
            f"a2a-signing:{self.tenant_id}:{instance_id}".encode(),
            hashlib.sha256,
        ).digest()

    def derive_encryption_key(self, instance_id: str) -> bytes:
        """Derive a per-instance encryption key for AES-256-GCM."""
        source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
        return hmac.new(
            source.encode(),
            f"a2a-encryption:{self.tenant_id}:{instance_id}".encode(),
            hashlib.sha256,
        ).digest()

    async def sign_message(
        self,
        *,
        from_instance: str,
        to_instance: str,
        content: dict[str, Any],
        message_type: str = "request",
        correlation_id: str = "",
        encrypt: bool = False,
    ) -> SecureMessage:
        """Create a signed (and optionally encrypted) message."""
        msg_id = uuid.uuid4().hex
        timestamp = time.time()

        # Get next sequence number (atomic increment)
        seq_num = await self._next_sequence_number(from_instance, to_instance)

        # Compute content hash for integrity
        content_json = json.dumps(content, sort_keys=True, separators=(",", ":"))
        message_hash = hashlib.sha256(content_json.encode()).hexdigest()

        # Optionally encrypt the content
        final_content = content
        is_encrypted = False
        if encrypt and settings.AGENT_A2A_ENCRYPTION_ENABLED:
            encryption_key = self.derive_encryption_key(to_instance)
            final_content = self._encrypt_content(content_json, encryption_key)
            is_encrypted = True

        msg = SecureMessage(
            id=msg_id,
            from_instance=from_instance,
            to_instance=to_instance,
            message_type=message_type,
            content=final_content,
            correlation_id=correlation_id or uuid.uuid4().hex,
            timestamp=timestamp,
            message_hash=message_hash,
            sequence_number=seq_num,
            encrypted=is_encrypted,
        )

        # Sign the message
        if settings.AGENT_A2A_SIGNING_ENABLED:
            signing_key = self.derive_signing_key(from_instance)
            msg.signature = self._compute_signature(msg, signing_key)

        return msg

    async def verify_message(self, msg: SecureMessage) -> tuple[bool, str]:
        """Verify a received message's signature, integrity, freshness, and sequence.

        Returns (is_valid, error_reason).
        """
        # 1. Check message freshness (prevent stale message attacks)
        age = abs(time.time() - msg.timestamp)
        if age > _MAX_CLOCK_SKEW_SECONDS:
            return False, f"Message too old ({age:.0f}s > {_MAX_CLOCK_SKEW_SECONDS}s)"

        # 2. Verify signature
        if settings.AGENT_A2A_SIGNING_ENABLED:
            if not msg.signature:
                return False, "Missing message signature"
            signing_key = self.derive_signing_key(msg.from_instance)
            expected_sig = self._compute_signature(msg, signing_key)
            if not hmac.compare_digest(msg.signature, expected_sig):
                await self._emit_security_event(msg, "signature_invalid")
                return False, "Invalid message signature"

        # 3. Verify replay protection (sequence number)
        is_replay = await self._check_replay(msg.from_instance, msg.to_instance, msg.sequence_number)
        if is_replay:
            await self._emit_security_event(msg, "replay_detected")
            return False, "Replay detected (duplicate or out-of-order sequence number)"

        # 4. Verify content integrity
        if not msg.encrypted:
            content_json = json.dumps(msg.content, sort_keys=True, separators=(",", ":"))
            content_hash = hashlib.sha256(content_json.encode()).hexdigest()
            if content_hash != msg.message_hash:
                return False, "Message integrity check failed (content hash mismatch)"

        # 5. Cross-agent injection defense
        if not msg.encrypted:
            injection_found = self._check_cross_agent_injection(msg.content)
            if injection_found:
                await self._emit_security_event(msg, "injection_detected")
                return False, f"Cross-agent injection detected: {injection_found}"

        return True, ""

    def decrypt_message(self, msg: SecureMessage) -> dict[str, Any]:
        """Decrypt an encrypted message's content."""
        if not msg.encrypted:
            return msg.content

        encryption_key = self.derive_encryption_key(msg.to_instance)
        return self._decrypt_content(msg.content, encryption_key)

    # ── Internal helpers ──────────────────────────────────────────────

    def _compute_signature(self, msg: SecureMessage, signing_key: bytes) -> str:
        """Compute HMAC-SHA256 signature over message fields."""
        payload = json.dumps({
            "id": msg.id,
            "from": msg.from_instance,
            "to": msg.to_instance,
            "type": msg.message_type,
            "hash": msg.message_hash,
            "seq": msg.sequence_number,
            "ts": msg.timestamp,
        }, sort_keys=True, separators=(",", ":"))
        return hmac.new(signing_key, payload.encode(), hashlib.sha256).hexdigest()

    async def _next_sequence_number(self, from_id: str, to_id: str) -> int:
        """Get the next monotonic sequence number for a sender+recipient pair."""
        seq_key = _SEQ_KEY.format(tenant_id=self.tenant_id, from_id=from_id, to_id=to_id)
        try:
            pipe = redis_pool.pipeline()
            pipe.incr(seq_key)
            pipe.expire(seq_key, 86400)
            results = await pipe.execute()
            return results[0]
        except Exception:
            logger.debug("a2a_seq_increment_failed", exc_info=True)
            return 0

    async def _check_replay(self, from_id: str, to_id: str, seq_num: int) -> bool:
        """Check if a sequence number has already been seen (replay detection)."""
        if seq_num <= 0:
            return False  # Sequence tracking unavailable
        seen_key = f"agent:a2a:seen:{self.tenant_id}:{to_id}:{from_id}"
        try:
            last_seen = await redis_pool.get(seen_key)
            last_seq = int(last_seen) if last_seen else 0
            if seq_num <= last_seq:
                return True  # Replay or out-of-order
            await redis_pool.setex(seen_key, 86400, str(seq_num))
            return False
        except Exception:
            logger.debug("a2a_replay_check_failed", exc_info=True)
            return False

    def _encrypt_content(self, content_json: str, key: bytes) -> dict[str, Any]:
        """Encrypt message content using AES-256-GCM."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, content_json.encode(), None)

        return {
            "__encrypted": True,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }

    def _decrypt_content(self, encrypted_data: dict[str, Any], key: bytes) -> dict[str, Any]:
        """Decrypt AES-256-GCM encrypted content."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = base64.b64decode(encrypted_data["nonce"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext"])
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())

    def _check_cross_agent_injection(self, content: dict[str, Any]) -> str:
        """Check message content for cross-agent injection patterns."""
        from app.ai.prompt_firewall import PromptFirewall

        firewall = PromptFirewall(tenant_id=self.tenant_id)
        # Scan all string values in the content dict
        for key, value in content.items():
            if not isinstance(value, str):
                continue
            result = firewall.scan_output(value, target_agent=True)
            if not result.passed:
                return result.violations[0]["detail"] if result.violations else "unknown"
        return ""

    async def _emit_security_event(self, msg: SecureMessage, issue: str) -> None:
        """Emit a security event for A2A communication issues."""
        from app.agents.events import A2AMessageSecurityEvent
        from app.core.events import emit

        try:
            await emit(
                A2AMessageSecurityEvent(
                    tenant_id=self.tenant_id,
                    from_instance=msg.from_instance,
                    to_instance=msg.to_instance,
                    issue=issue,
                ),
                durable=True,
            )
        except Exception:
            logger.debug("a2a_security_event_failed", exc_info=True)

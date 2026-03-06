"""Prepaid token wallet with Redis hot-path and DB persistence.

Implements atomic balance operations via Redis Lua scripts to prevent
race conditions during concurrent AI requests. DB is used for durable
storage and the immutable transaction ledger.

Margin model:
  - Platform-managed keys: 20% margin (platform bears provider cost)
  - BYOK keys: 5% infrastructure fee (tenant pays provider directly)
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool
from app.db.models.ai import TokenWallet, WalletTransaction, WalletTransactionType

logger = structlog.stdlib.get_logger()

# Redis key prefix for wallet balances
_WALLET_KEY_PREFIX = "wallet:balance:"

# ── Lua Scripts ───────────────────────────────────────────
# Atomic check-and-deduct: returns new balance or -1 if insufficient.
_DEDUCT_SCRIPT = """
local balance = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
if balance < amount then
    return -1
end
local new_balance = balance - amount
redis.call('SET', KEYS[1], new_balance)
return new_balance
"""

# Atomic refund (add back tokens, no upper-bound check needed).
_REFUND_SCRIPT = """
local balance = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
local new_balance = balance + amount
redis.call('SET', KEYS[1], new_balance)
return new_balance
"""


def _balance_key(tenant_id: uuid.UUID) -> str:
    return f"{_WALLET_KEY_PREFIX}{tenant_id}"


class InsufficientBalanceError(Exception):
    """Raised when a tenant's wallet balance is too low for an operation."""

    def __init__(self, tenant_id: uuid.UUID, required: int, available: int):
        self.tenant_id = tenant_id
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient balance: required {required} tokens, available {available}"
        )


class TokenWalletService:
    """Manages prepaid token wallet operations."""

    async def get_balance(self, tenant_id: uuid.UUID) -> int:
        """Get current token balance from Redis (fast path)."""
        try:
            val = await redis_pool.get(_balance_key(tenant_id))
            if val is not None:
                return int(val)
        except Exception:
            logger.warning("wallet_redis_read_error", tenant_id=str(tenant_id))
        return 0

    async def deduct_tokens(
        self,
        tenant_id: uuid.UUID,
        amount: int,
        *,
        description: str = "",
        reference_id: str | None = None,
        db: AsyncSession,
    ) -> int:
        """Atomically deduct tokens from wallet.

        Returns new balance. Raises InsufficientBalanceError if balance too low.
        Also records a WalletTransaction in the DB for the audit ledger.
        """
        if amount <= 0:
            return await self.get_balance(tenant_id)

        key = _balance_key(tenant_id)
        try:
            new_balance = await redis_pool.eval(_DEDUCT_SCRIPT, 1, key, str(amount))
            new_balance = int(new_balance)
        except Exception:
            logger.error("wallet_deduct_redis_error", tenant_id=str(tenant_id))
            raise

        if new_balance < 0:
            # Deduction was rejected — balance insufficient
            current = await self.get_balance(tenant_id)
            raise InsufficientBalanceError(tenant_id, amount, current)

        # Record transaction in DB
        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.CONSUMPTION,
            amount_tokens=-amount,
            balance_after=new_balance,
            description=description or "AI token consumption",
            reference_id=reference_id,
        )
        db.add(tx)

        # Update DB wallet record
        await self._update_db_wallet(tenant_id, db, consumed=amount)

        try:
            await db.commit()
        except Exception:
            logger.error("wallet_tx_commit_error", tenant_id=str(tenant_id))
            await db.rollback()
            # Redis already deducted — DB will reconcile on next sync
            raise

        return new_balance

    async def refund_tokens(
        self,
        tenant_id: uuid.UUID,
        amount: int,
        *,
        description: str = "",
        reference_id: str | None = None,
        db: AsyncSession,
    ) -> int:
        """Refund tokens to wallet (e.g., after failed AI call)."""
        if amount <= 0:
            return await self.get_balance(tenant_id)

        key = _balance_key(tenant_id)
        try:
            new_balance = int(await redis_pool.eval(_REFUND_SCRIPT, 1, key, str(amount)))
        except Exception:
            logger.error("wallet_refund_redis_error", tenant_id=str(tenant_id))
            raise

        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.REFUND,
            amount_tokens=amount,
            balance_after=new_balance,
            description=description or "AI token refund",
            reference_id=reference_id,
        )
        db.add(tx)
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        return new_balance

    async def topup(
        self,
        tenant_id: uuid.UUID,
        amount_tokens: int,
        *,
        reference_id: str | None = None,
        description: str = "",
        db: AsyncSession,
    ) -> int:
        """Credit tokens to wallet after payment.

        Returns new balance.
        """
        if amount_tokens <= 0:
            raise ValueError("Topup amount must be positive")

        key = _balance_key(tenant_id)

        # Add to Redis
        try:
            new_balance = int(await redis_pool.eval(_REFUND_SCRIPT, 1, key, str(amount_tokens)))
        except Exception:
            logger.error("wallet_topup_redis_error", tenant_id=str(tenant_id))
            raise

        # Ensure wallet record exists in DB
        wallet = await self._get_or_create_wallet(tenant_id, db)
        wallet.balance_tokens = new_balance
        wallet.lifetime_purchased += amount_tokens

        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.TOPUP,
            amount_tokens=amount_tokens,
            balance_after=new_balance,
            description=description or "Token wallet topup",
            reference_id=reference_id,
        )
        db.add(tx)

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        logger.info(
            "wallet_topup",
            tenant_id=str(tenant_id),
            amount=amount_tokens,
            new_balance=new_balance,
        )
        return new_balance

    async def initialize_balance(self, tenant_id: uuid.UUID, db: AsyncSession) -> None:
        """Load wallet balance from DB into Redis (called on first access or startup)."""
        wallet = await self._get_or_create_wallet(tenant_id, db)
        key = _balance_key(tenant_id)
        try:
            await redis_pool.set(key, str(wallet.balance_tokens))
        except Exception:
            logger.warning("wallet_init_redis_error", tenant_id=str(tenant_id))

    async def _get_or_create_wallet(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> TokenWallet:
        """Get existing wallet or create a new one with zero balance."""
        result = await db.execute(
            select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = TokenWallet(tenant_id=tenant_id, balance_tokens=0)
            db.add(wallet)
            try:
                await db.commit()
                await db.refresh(wallet)
            except Exception:
                await db.rollback()
                # Race condition: another request created it first
                result = await db.execute(
                    select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
                )
                wallet = result.scalar_one()
        return wallet

    async def _update_db_wallet(
        self, tenant_id: uuid.UUID, db: AsyncSession, *, consumed: int = 0
    ) -> None:
        """Update the DB wallet record (balance + lifetime counters)."""
        result = await db.execute(
            select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            # Get current Redis balance as source of truth
            balance = await self.get_balance(tenant_id)
            wallet.balance_tokens = balance
            wallet.lifetime_consumed += consumed


# Module-level singleton
wallet_service = TokenWalletService()

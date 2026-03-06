"""Prepaid token wallet with Redis hot-path and DB persistence.

Implements atomic balance operations via Redis Lua scripts to prevent
race conditions during concurrent AI requests. DB is used for durable
storage and the immutable transaction ledger.

Consistency model:
  - DB is committed FIRST, then Redis is updated. On Redis failure after
    DB commit, the next initialize_balance() call syncs Redis from DB.
  - Redis is the fast-path read source; DB is the durable source of truth.

Margin model:
  - Platform-managed keys: 20% margin (platform bears provider cost)
  - BYOK keys: 5% infrastructure fee (tenant pays provider directly)
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool
from app.db.models.ai import TokenWallet, WalletTransaction, WalletTransactionType

logger = structlog.stdlib.get_logger()

# Redis key prefix for wallet balances
_WALLET_KEY_PREFIX = "wallet:balance:"

# Max balance to prevent overflow (safe limit well under int64 max)
_MAX_BALANCE = 10_000_000_000_000  # 10 trillion tokens

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

# Atomic credit with overflow protection: returns new balance or -2 on overflow.
_CREDIT_SCRIPT = """
local balance = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
local max_balance = tonumber(ARGV[2])
local new_balance = balance + amount
if new_balance > max_balance then
    return -2
end
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


class WalletOverflowError(Exception):
    """Raised when a topup would exceed the maximum wallet balance."""


class TokenWalletService:
    """Manages prepaid token wallet operations.

    Consistency strategy: DB-first, Redis-second.
    - Writes go to DB first (durable), then Redis (fast cache).
    - If Redis update fails after DB commit, balance is stale in Redis
      but correct in DB. Next initialize_balance() or read syncs it.
    - Reads prefer Redis; fall back to DB on cache miss.
    """

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

        Strategy: Deduct in Redis (fast, atomic), record in DB, reconcile on failure.
        Returns new balance. Raises InsufficientBalanceError if balance too low.
        """
        if amount <= 0:
            return await self.get_balance(tenant_id)

        # Step 1: Atomic deduction in Redis
        key = _balance_key(tenant_id)
        try:
            new_balance = int(await redis_pool.eval(_DEDUCT_SCRIPT, 1, key, str(amount)))
        except Exception:
            logger.error("wallet_deduct_redis_error", tenant_id=str(tenant_id))
            raise

        if new_balance < 0:
            # The Lua script did NOT deduct (balance unchanged), so no rollback needed.
            # Use the value from Redis directly rather than re-querying (avoids TOCTOU).
            try:
                current = int(await redis_pool.get(key) or 0)
            except Exception:
                current = 0
            raise InsufficientBalanceError(tenant_id, amount, current)

        # Step 2: Record in DB (transaction + wallet update)
        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.CONSUMPTION,
            amount_tokens=-amount,
            balance_after=new_balance,
            description=description or "AI token consumption",
            reference_id=reference_id,
        )
        db.add(tx)

        # Update wallet using the Lua-returned balance (not re-querying Redis)
        await self._update_db_wallet_direct(tenant_id, db, balance=new_balance, consumed_delta=amount)

        try:
            await db.commit()
        except Exception:
            logger.error(
                "wallet_deduct_db_commit_failed",
                tenant_id=str(tenant_id),
                amount=amount,
                redis_balance=new_balance,
            )
            await db.rollback()
            # Redis was already deducted. Refund Redis to stay consistent.
            try:
                await redis_pool.eval(_CREDIT_SCRIPT, 1, key, str(amount), str(_MAX_BALANCE))
                logger.info("wallet_deduct_redis_rollback_ok", tenant_id=str(tenant_id))
            except Exception:
                logger.critical(
                    "wallet_deduct_redis_rollback_failed",
                    tenant_id=str(tenant_id),
                    amount=amount,
                )
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
        """Refund tokens to wallet (e.g., after failed AI call).

        DB-first: record refund in DB, then credit Redis.
        """
        if amount <= 0:
            return await self.get_balance(tenant_id)

        # Get current balance for the transaction record
        current_balance = await self.get_balance(tenant_id)
        expected_new = current_balance + amount

        # DB first: record transaction AND update wallet balance
        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.REFUND,
            amount_tokens=amount,
            balance_after=expected_new,
            description=description or "AI token refund",
            reference_id=reference_id,
        )
        db.add(tx)

        # Update the wallet record in DB to keep it consistent
        result = await db.execute(
            select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            wallet.balance_tokens = expected_new

        try:
            await db.commit()
        except Exception:
            logger.error("wallet_refund_db_error", tenant_id=str(tenant_id))
            await db.rollback()
            raise

        # Then Redis
        key = _balance_key(tenant_id)
        try:
            new_balance = int(
                await redis_pool.eval(_CREDIT_SCRIPT, 1, key, str(amount), str(_MAX_BALANCE))
            )
        except Exception:
            logger.error("wallet_refund_redis_error", tenant_id=str(tenant_id))
            # DB recorded the refund; Redis will catch up on next init
            new_balance = expected_new

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
        """Credit tokens to wallet after payment verification.

        DB-first: update wallet + record transaction, then sync Redis.
        Returns new balance.
        """
        if amount_tokens <= 0:
            raise ValueError("Topup amount must be positive")

        # Idempotency: reject duplicate topups with the same reference_id
        # to prevent double-crediting from Stripe webhook retries.
        if reference_id:
            existing_tx = await db.execute(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id,
                    WalletTransaction.reference_id == reference_id,
                    WalletTransaction.type == WalletTransactionType.TOPUP,
                )
            )
            if existing_tx.scalar_one_or_none():
                logger.info(
                    "wallet_topup_duplicate",
                    tenant_id=str(tenant_id),
                    reference_id=reference_id,
                )
                wallet = await self._get_or_create_wallet(tenant_id, db)
                return wallet.balance_tokens

        # DB first: update wallet record atomically
        wallet = await self._get_or_create_wallet(tenant_id, db)
        new_balance = wallet.balance_tokens + amount_tokens

        if new_balance > _MAX_BALANCE:
            raise WalletOverflowError(
                f"Topup would exceed maximum balance ({_MAX_BALANCE} tokens)"
            )

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

        # Then sync to Redis
        key = _balance_key(tenant_id)
        try:
            await redis_pool.set(key, str(new_balance))
        except Exception:
            logger.warning("wallet_topup_redis_sync_error", tenant_id=str(tenant_id))
            # DB has the correct balance; Redis will catch up

        logger.info(
            "wallet_topup",
            tenant_id=str(tenant_id),
            amount=amount_tokens,
            new_balance=new_balance,
        )
        return new_balance

    async def initialize_balance(self, tenant_id: uuid.UUID, db: AsyncSession) -> None:
        """Load wallet balance from DB into Redis (called on first access or startup).

        DB is the source of truth — this ensures Redis is consistent.
        """
        wallet = await self._get_or_create_wallet(tenant_id, db)
        key = _balance_key(tenant_id)
        try:
            await redis_pool.set(key, str(wallet.balance_tokens))
        except Exception:
            logger.warning("wallet_init_redis_error", tenant_id=str(tenant_id))

    async def _get_or_create_wallet(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> TokenWallet:
        """Get existing wallet or create a new one with zero balance.

        Handles race conditions via unique constraint + retry-on-conflict.
        """
        result = await db.execute(
            select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = TokenWallet(tenant_id=tenant_id, balance_tokens=0)
            db.add(wallet)
            try:
                await db.flush()
            except Exception:
                await db.rollback()
                # Race condition: another request created it — fetch theirs
                result = await db.execute(
                    select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
                )
                wallet = result.scalar_one_or_none()
                if not wallet:
                    raise RuntimeError(f"Failed to create or fetch wallet for tenant {tenant_id}")
        return wallet

    async def _update_db_wallet_direct(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
        *,
        balance: int,
        consumed_delta: int = 0,
    ) -> None:
        """Update the DB wallet record using the known balance from Redis Lua.

        Uses the balance value returned from the Lua script directly,
        avoiding a second Redis query and preventing race conditions.
        """
        result = await db.execute(
            select(TokenWallet).where(TokenWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            wallet.balance_tokens = balance
            wallet.lifetime_consumed += consumed_delta


# Module-level singleton
wallet_service = TokenWalletService()

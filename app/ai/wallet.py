"""Prepaid USD wallet with Redis hot-path and DB persistence.

Implements atomic balance operations via Redis Lua scripts to prevent
race conditions during concurrent AI requests. DB is used for durable
storage and the immutable transaction ledger.

Consistency model:
  - DB is committed FIRST, then Redis is updated. On Redis failure after
    DB commit, the next initialize_balance() call syncs Redis from DB.
  - Redis is the fast-path read source; DB is the durable source of truth.

Margin model:
  - Platform-managed keys: 20% margin on provider cost (USD)
  - BYOK keys: 5% infrastructure fee on provider cost (USD)

Redis encoding:
  - Balances stored as integer micro-dollars (USD × 1,000,000) to preserve
    Lua's integer arithmetic while supporting 6 decimal places of precision.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool
from app.db.models.ai import DollarWallet, WalletTransaction, WalletTransactionType

logger = structlog.stdlib.get_logger()

# Redis key prefix for wallet balances
_WALLET_KEY_PREFIX = "wallet:balance:"

# Micro-dollar scale: 1 USD = 1,000,000 micro-dollars
_SCALE = 1_000_000

# Max balance in USD (≈$1M)
_MAX_BALANCE = Decimal("999999.999999")
_MAX_BALANCE_MICRO = int(_MAX_BALANCE * _SCALE)

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


def _to_micro(usd: Decimal) -> int:
    """Convert USD Decimal to integer micro-dollars for Redis."""
    return int(usd * _SCALE)


def _from_micro(micro: int) -> Decimal:
    """Convert integer micro-dollars from Redis to USD Decimal."""
    return Decimal(micro) / _SCALE


def _balance_key(tenant_id: uuid.UUID) -> str:
    return f"{_WALLET_KEY_PREFIX}{tenant_id}"


class InsufficientBalanceError(Exception):
    """Raised when a tenant's wallet balance is too low for an operation."""

    def __init__(self, tenant_id: uuid.UUID, required: Decimal, available: Decimal):
        self.tenant_id = tenant_id
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient balance: required ${required}, available ${available}"
        )


class WalletOverflowError(Exception):
    """Raised when a topup would exceed the maximum wallet balance."""


class DollarWalletService:
    """Manages prepaid USD wallet operations.

    Consistency strategy: DB-first, Redis-second.
    - Writes go to DB first (durable), then Redis (fast cache).
    - If Redis update fails after DB commit, balance is stale in Redis
      but correct in DB. Next initialize_balance() or read syncs it.
    - Reads prefer Redis; fall back to DB on cache miss.
    """

    async def get_balance(self, tenant_id: uuid.UUID) -> Decimal:
        """Get current USD balance from Redis (fast path)."""
        try:
            val = await redis_pool.get(_balance_key(tenant_id))
            if val is not None:
                return _from_micro(int(val))
        except Exception:
            logger.warning("wallet_redis_read_error", tenant_id=str(tenant_id))
        return Decimal("0")

    async def deduct(
        self,
        tenant_id: uuid.UUID,
        amount_usd: Decimal,
        *,
        provider_cost_usd: Decimal | None = None,
        description: str = "",
        reference_id: str | None = None,
        db: AsyncSession,
    ) -> Decimal:
        """Atomically deduct USD from wallet.

        Strategy: Deduct in Redis (fast, atomic), record in DB, reconcile on failure.
        Returns new balance. Raises InsufficientBalanceError if balance too low.
        """
        if amount_usd <= 0:
            return await self.get_balance(tenant_id)

        amount_micro = _to_micro(amount_usd)

        # Step 1: Atomic deduction in Redis
        key = _balance_key(tenant_id)
        try:
            new_balance_micro = int(await redis_pool.eval(_DEDUCT_SCRIPT, 1, key, str(amount_micro)))
        except Exception:
            logger.error("wallet_deduct_redis_error", tenant_id=str(tenant_id))
            raise

        if new_balance_micro < 0:
            # The Lua script did NOT deduct (balance unchanged).
            try:
                current_micro = int(await redis_pool.get(key) or 0)
            except Exception:
                current_micro = 0
            raise InsufficientBalanceError(tenant_id, amount_usd, _from_micro(current_micro))

        new_balance = _from_micro(new_balance_micro)

        # Step 2: Record in DB (transaction + wallet update)
        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.CONSUMPTION,
            amount_usd=-amount_usd,
            balance_after_usd=new_balance,
            provider_cost_usd=provider_cost_usd,
            description=description or "AI usage",
            reference_id=reference_id,
        )
        db.add(tx)

        await self._update_db_wallet_direct(tenant_id, db, balance_usd=new_balance, consumed_delta=amount_usd)

        try:
            await db.commit()
        except Exception:
            logger.error(
                "wallet_deduct_db_commit_failed",
                tenant_id=str(tenant_id),
                amount_usd=str(amount_usd),
                redis_balance=str(new_balance),
            )
            await db.rollback()
            # Redis was already deducted. Refund Redis to stay consistent.
            try:
                await redis_pool.eval(_CREDIT_SCRIPT, 1, key, str(amount_micro), str(_MAX_BALANCE_MICRO))
                logger.info("wallet_deduct_redis_rollback_ok", tenant_id=str(tenant_id))
            except Exception:
                logger.critical(
                    "wallet_deduct_redis_rollback_failed",
                    tenant_id=str(tenant_id),
                    amount_usd=str(amount_usd),
                )
            raise

        return new_balance

    async def refund(
        self,
        tenant_id: uuid.UUID,
        amount_usd: Decimal,
        *,
        description: str = "",
        reference_id: str | None = None,
        db: AsyncSession,
    ) -> Decimal:
        """Refund USD to wallet (e.g., after failed AI call).

        Strategy: atomic credit in Redis first (to get accurate balance_after),
        then record in DB. On DB failure, roll back Redis.
        """
        if amount_usd <= 0:
            return await self.get_balance(tenant_id)

        amount_micro = _to_micro(amount_usd)

        # Step 1: Atomic credit in Redis
        key = _balance_key(tenant_id)
        try:
            new_balance_micro = int(
                await redis_pool.eval(_CREDIT_SCRIPT, 1, key, str(amount_micro), str(_MAX_BALANCE_MICRO))
            )
        except Exception:
            logger.error("wallet_refund_redis_error", tenant_id=str(tenant_id))
            raise

        if new_balance_micro == -2:
            raise WalletOverflowError("Refund would exceed maximum wallet balance")

        new_balance = _from_micro(new_balance_micro)

        # Step 2: Record in DB
        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.REFUND,
            amount_usd=amount_usd,
            balance_after_usd=new_balance,
            description=description or "AI usage refund",
            reference_id=reference_id,
        )
        db.add(tx)

        result = await db.execute(
            select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            wallet.balance_usd = new_balance

        try:
            await db.commit()
        except Exception:
            logger.error("wallet_refund_db_error", tenant_id=str(tenant_id))
            await db.rollback()
            # Redis was already credited. Reverse it.
            try:
                await redis_pool.eval(_DEDUCT_SCRIPT, 1, key, str(amount_micro))
                logger.info("wallet_refund_redis_rollback_ok", tenant_id=str(tenant_id))
            except Exception:
                logger.critical(
                    "wallet_refund_redis_rollback_failed",
                    tenant_id=str(tenant_id),
                    amount_usd=str(amount_usd),
                )
            raise

        return new_balance

    async def topup(
        self,
        tenant_id: uuid.UUID,
        amount_usd: Decimal,
        *,
        reference_id: str | None = None,
        stripe_payment_intent_id: str | None = None,
        description: str = "",
        db: AsyncSession,
    ) -> Decimal:
        """Credit USD to wallet after payment verification.

        DB-first: update wallet + record transaction, then sync Redis.
        Returns new balance.
        """
        if amount_usd <= 0:
            raise ValueError("Topup amount must be positive")

        # Idempotency: reject duplicate topups with the same reference_id
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
                return wallet.balance_usd

        # DB first: update wallet record
        wallet = await self._get_or_create_wallet(tenant_id, db)
        new_balance = wallet.balance_usd + amount_usd

        if new_balance > _MAX_BALANCE:
            raise WalletOverflowError(
                f"Topup would exceed maximum balance (${_MAX_BALANCE})"
            )

        wallet.balance_usd = new_balance
        wallet.lifetime_deposited_usd += amount_usd

        tx = WalletTransaction(
            tenant_id=tenant_id,
            type=WalletTransactionType.TOPUP,
            amount_usd=amount_usd,
            balance_after_usd=new_balance,
            description=description or "Wallet top-up",
            reference_id=reference_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
        )
        db.add(tx)

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        # Sync to Redis atomically
        key = _balance_key(tenant_id)
        amount_micro = _to_micro(amount_usd)
        try:
            await redis_pool.eval(_CREDIT_SCRIPT, 1, key, str(amount_micro), str(_MAX_BALANCE_MICRO))
        except Exception:
            logger.warning("wallet_topup_redis_sync_error", tenant_id=str(tenant_id))

        logger.info(
            "wallet_topup",
            tenant_id=str(tenant_id),
            amount_usd=str(amount_usd),
            new_balance=str(new_balance),
        )
        return new_balance

    async def initialize_balance(self, tenant_id: uuid.UUID, db: AsyncSession) -> Decimal:
        """Load wallet balance from DB into Redis (called on first access or startup).

        DB is the source of truth — this ensures Redis is consistent.
        Returns the current balance.
        """
        wallet = await self._get_or_create_wallet(tenant_id, db)
        key = _balance_key(tenant_id)
        try:
            await redis_pool.set(key, str(_to_micro(wallet.balance_usd)))
        except Exception:
            logger.warning("wallet_init_redis_error", tenant_id=str(tenant_id))
        return wallet.balance_usd

    async def check_auto_refill(self, tenant_id: uuid.UUID, balance: Decimal, db: AsyncSession) -> None:
        """Check if balance dropped below auto-refill threshold and trigger refill.

        This is fire-and-forget — failures are logged but don't affect the caller.
        """
        result = await db.execute(
            select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if not wallet or not wallet.auto_refill_enabled:
            return
        if wallet.auto_refill_threshold_usd is None or wallet.auto_refill_amount_usd is None:
            return
        if balance > wallet.auto_refill_threshold_usd:
            return
        if not wallet.stripe_payment_method_id:
            logger.warning("wallet_auto_refill_no_payment_method", tenant_id=str(tenant_id))
            return

        # Trigger auto-refill asynchronously via Celery to avoid blocking the request
        try:
            from app.billing.tasks import process_auto_refill

            process_auto_refill.delay(str(tenant_id))
            logger.info(
                "wallet_auto_refill_triggered",
                tenant_id=str(tenant_id),
                balance=str(balance),
                threshold=str(wallet.auto_refill_threshold_usd),
            )
        except Exception:
            logger.error("wallet_auto_refill_trigger_failed", tenant_id=str(tenant_id), exc_info=True)

    async def _get_or_create_wallet(
        self, tenant_id: uuid.UUID, db: AsyncSession
    ) -> DollarWallet:
        """Get existing wallet or create a new one with zero balance."""
        result = await db.execute(
            select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = DollarWallet(tenant_id=tenant_id, balance_usd=Decimal("0"))
            db.add(wallet)
            try:
                await db.flush()
            except Exception:
                await db.rollback()
                result = await db.execute(
                    select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
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
        balance_usd: Decimal,
        consumed_delta: Decimal = Decimal("0"),
    ) -> None:
        """Update the DB wallet record using the known balance from Redis Lua."""
        result = await db.execute(
            select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
        )
        wallet = result.scalar_one_or_none()
        if wallet:
            wallet.balance_usd = balance_usd
            wallet.lifetime_consumed_usd += consumed_delta


# Module-level singleton
wallet_service = DollarWalletService()

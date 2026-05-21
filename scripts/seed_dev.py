"""Seed development database with a test user for local testing.

Usage:
    python -m scripts.seed_dev

Creates:
    - Tenant: "dev-team" (slug: dev-team)
    - User: admin@test.com / TestPass123
    - Role: owner (email pre-verified, ready to login)
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models import Tenant, TenantMembership, User, UserRole
from app.db.session import async_session_factory, dispose_engines

# Test credentials
TEST_EMAIL = "admin@test.com"
TEST_PASSWORD = "TestPass123"
TEST_DISPLAY_NAME = "Dev Admin"
TEST_TENANT_NAME = "Dev Team"
TEST_TENANT_SLUG = "dev-team"


async def seed(session: AsyncSession) -> None:
    # Check if user already exists
    existing = await session.execute(select(User).where(User.email == TEST_EMAIL, User.deleted_at.is_(None)))
    if existing.scalar_one_or_none():
        print(f"User {TEST_EMAIL} already exists — skipping seed.")
        return

    # Check if tenant slug already exists
    existing_tenant = await session.execute(select(Tenant).where(Tenant.slug == TEST_TENANT_SLUG))
    tenant = existing_tenant.scalar_one_or_none()

    if not tenant:
        tenant = Tenant(name=TEST_TENANT_NAME, slug=TEST_TENANT_SLUG, plan="enterprise")
        session.add(tenant)
        await session.flush()
        print(f"Created tenant: {TEST_TENANT_NAME} ({TEST_TENANT_SLUG})")
    elif tenant.plan != "enterprise":
        tenant.plan = "enterprise"
        print("Upgraded tenant plan to enterprise")

    user = User(
        tenant_id=tenant.id,
        email=TEST_EMAIL,
        password_hash=hash_password(TEST_PASSWORD),
        display_name=TEST_DISPLAY_NAME,
        email_verified=True,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=UserRole.OWNER,
    )
    session.add(membership)

    await session.commit()
    print(f"Created user: {TEST_EMAIL} / {TEST_PASSWORD} (role: owner)")
    print("Ready to login at http://localhost:3000/login")


async def main() -> None:
    async with async_session_factory() as session:
        await seed(session)
    await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())

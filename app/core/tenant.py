"""Tenant-scoped query helpers.

Usage in route handlers:

    from app.core.tenant import tenant_query

    @router.get("/jobs")
    async def list_jobs(
        tenant: Tenant = Depends(get_current_tenant),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = tenant_query(select(Job), tenant).where(Job.status == JobStatus.COMPLETED)
        result = await db.execute(stmt)
        return result.scalars().all()
"""

from sqlalchemy import Select


def tenant_query(stmt: Select, tenant) -> Select:
    """Add a WHERE tenant_id = :id filter to any SELECT that has a tenant_id column."""
    entity = stmt.columns_clause_froms[0] if stmt.columns_clause_froms else None
    if entity is not None and hasattr(entity.c, "tenant_id"):
        return stmt.where(entity.c.tenant_id == tenant.id)
    return stmt

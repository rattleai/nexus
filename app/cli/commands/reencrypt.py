"""CLI command to re-encrypt v1 (Fernet) ciphertexts to v2 (AES-256-GCM).

Usage:
    cadprice reencrypt --dry-run    # Show what would be updated
    cadprice reencrypt              # Actually re-encrypt
"""

from __future__ import annotations

import structlog

logger = structlog.stdlib.get_logger()

# Tables and columns that contain encrypted data
_ENCRYPTED_COLUMNS = [
    ("tenant_ai_provider_keys", "encrypted_api_key"),
    ("sso_configurations", "client_secret_encrypted"),
    ("oauth_accounts", "access_token"),
    ("oauth_accounts", "refresh_token"),
]


def reencrypt_all(dry_run: bool = False) -> dict[str, int]:
    """Re-encrypt all v1 ciphertexts to v2 across all tables.

    Returns a dict of {table.column: count_updated}.
    """
    from sqlalchemy import create_engine, text

    from app.config import settings
    from app.core.encryption import decrypt, encrypt

    # Use sync engine for CLI operations
    sync_url = str(settings.DATABASE_URL).replace("+asyncpg", "+psycopg2").replace("postgresql://", "postgresql+psycopg2://")
    if "+asyncpg" in sync_url:
        sync_url = sync_url.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    results = {}

    with engine.begin() as conn:
        for table, column in _ENCRYPTED_COLUMNS:
            key = f"{table}.{column}"
            updated = 0

            # Find all rows with v1 ciphertexts
            rows = conn.execute(text(
                f'SELECT id, "{column}" FROM "{table}" '  # noqa: S608
                f'WHERE "{column}" IS NOT NULL '
                f"AND (\"{column}\" LIKE 'v1:%%' OR \"{column}\" NOT LIKE 'v2:%%')"
            )).fetchall()

            for row in rows:
                row_id, ciphertext = row
                if not ciphertext:
                    continue

                try:
                    plaintext = decrypt(ciphertext)
                    new_ciphertext = encrypt(plaintext)

                    if new_ciphertext == ciphertext:
                        continue  # Already v2

                    if dry_run:
                        print(f"  [DRY RUN] Would re-encrypt {table}.{column} id={row_id}")  # noqa: T201
                    else:
                        conn.execute(text(
                            f'UPDATE "{table}" SET "{column}" = :new_ct WHERE id = :id'  # noqa: S608
                        ), {"new_ct": new_ciphertext, "id": row_id})

                    updated += 1
                except Exception as exc:
                    logger.error(
                        "reencrypt_failed",
                        table=table,
                        column=column,
                        row_id=str(row_id),
                        error=str(exc),
                    )

            results[key] = updated
            if updated > 0:
                action = "would update" if dry_run else "updated"
                print(f"  {key}: {action} {updated} rows")  # noqa: T201

    return results

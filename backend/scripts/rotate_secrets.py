#!/usr/bin/env python3
"""Re-encrypt stored SSO secrets under the current SECRET_ENCRYPTION_KEY.

GeoLens encrypts ``catalog.oauth_providers.client_secret_encrypted`` and
``idp_certificate`` at rest. Reads try every configured key in turn, so a row
written under an older key keeps working; writes only ever use the newest one.
This script rewrites the rows still on an older key, which is what lets you
then retire that key (#1871).

Usage:
    docker compose exec api uv run python scripts/rotate_secrets.py --dry-run
    docker compose exec api uv run python scripts/rotate_secrets.py

Run it after setting SECRET_ENCRYPTION_KEY on an existing install, and after
replacing one SECRET_ENCRYPTION_KEY with another. RUNBOOK.md section 11 is the
operator procedure for both, including what each rotation invalidates.

Behaviour:

- Exits 2 when SECRET_ENCRYPTION_KEY is unset. Without it the newest key is the
  JWT-derived one, so a "rotation" would rewrite every row under the very key
  this setting exists to move them off.
- Decrypts every row before writing any of them. A row no configured key opens
  exits 1 and leaves the table untouched, because a partial rewrite would
  strand the rest behind a key you are about to retire.
- Idempotent. Re-running changes neither the plaintext nor which keys can read
  the rows.
- Prints provider ids and counts only, never key material, ciphertext, or a
  decrypted value.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class UndecryptableRowsError(RuntimeError):
    """Raised when rows do not open with any configured key. Nothing is written."""

    def __init__(self, provider_ids: list[str]) -> None:
        self.provider_ids = provider_ids
        super().__init__(
            f"{len(provider_ids)} oauth_providers row(s) do not decrypt with "
            "any configured key"
        )


async def rotate_oauth_provider_secrets(
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> int:
    """Re-encrypt every OAuth provider secret under the newest configured key.

    Returns the number of rows rewritten (the number that would be rewritten,
    under ``dry_run``). Raises :class:`UndecryptableRowsError` without writing
    anything when any row fails to decrypt.
    """
    from cryptography.fernet import InvalidToken

    from app.modules.auth.oauth.encryption import rotate_secret

    result = await db.execute(
        text(
            "SELECT id, client_secret_encrypted, idp_certificate "
            "FROM catalog.oauth_providers ORDER BY id"
        )
    )
    rows = result.fetchall()
    if not rows:
        print("No oauth_providers rows to rotate.")
        return 0

    # Decrypt everything first. A row that fails after some siblings were
    # already written would leave the table split across two keys.
    rewritten: list[tuple[object, str, str | None]] = []
    failed: list[str] = []
    for row in rows:
        try:
            new_secret = rotate_secret(row.client_secret_encrypted)
            new_certificate = (
                rotate_secret(row.idp_certificate) if row.idp_certificate else None
            )
        except InvalidToken:
            failed.append(str(row.id))
            continue
        rewritten.append((row.id, new_secret, new_certificate))

    if failed:
        for provider_id in failed:
            print(f"  UNDECRYPTABLE {provider_id}", file=sys.stderr)
        raise UndecryptableRowsError(failed)

    if dry_run:
        print(f"Would re-encrypt {len(rewritten)} oauth_providers row(s).")
        return len(rewritten)

    for provider_id, new_secret, new_certificate in rewritten:
        await db.execute(
            text(
                "UPDATE catalog.oauth_providers "
                "SET client_secret_encrypted = :secret, idp_certificate = :cert "
                "WHERE id = :id"
            ),
            {"secret": new_secret, "cert": new_certificate, "id": provider_id},
        )
    await db.commit()
    print(f"Re-encrypted {len(rewritten)} oauth_providers row(s).")
    return len(rewritten)


async def _run(dry_run: bool) -> int:
    from app.core.config import settings

    if settings.secret_encryption_key is None:
        print(
            "SECRET_ENCRYPTION_KEY is not set. Set it (and restart the API) "
            "before rotating: without it the newest key is still derived from "
            "JWT_SECRET_KEY, so this would rewrite every row under the key it "
            "is meant to move them off.",
            file=sys.stderr,
        )
        return 2

    engine = create_async_engine(settings.database_url, pool_size=2)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            try:
                await rotate_oauth_provider_secrets(db, dry_run=dry_run)
            except UndecryptableRowsError as exc:
                await db.rollback()
                print(
                    f"{exc}. Nothing was written. Add the key those rows were "
                    "written under as SECRET_ENCRYPTION_KEY_PREVIOUS, or "
                    "re-enter the affected providers' credentials in the admin "
                    "UI, then run this again.",
                    file=sys.stderr,
                )
                return 1
    finally:
        await engine.dispose()

    if settings.secret_encryption_key_previous is not None and not dry_run:
        print(
            "Every row now reads under SECRET_ENCRYPTION_KEY alone. Remove "
            "SECRET_ENCRYPTION_KEY_PREVIOUS from .env and restart."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-encrypt stored SSO secrets under the newest key."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be rewritten without writing anything.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

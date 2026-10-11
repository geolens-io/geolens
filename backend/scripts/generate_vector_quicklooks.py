"""Bulk-generate vector quicklook thumbnails for existing datasets.

Usage:
    docker compose exec api /app/.venv/bin/python scripts/generate_vector_quicklooks.py
    docker compose exec api /app/.venv/bin/python scripts/generate_vector_quicklooks.py --force

Without --force: only generates for datasets missing quicklooks.
With --force: regenerates all vector quicklooks (e.g., after renderer changes).

Multi-tenant mode is refused: there is no tenant context or tenant storage prefix.
"""

import asyncio
import io
import sys
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def _drop_unreferenced(db, storage, dataset_id, ql_key: str) -> None:
    """Delete an uploaded image unless the dataset's committed pointer names it."""
    try:
        current = await db.scalar(
            text("SELECT quicklook_256_uri FROM catalog.datasets WHERE id = :id"),
            {"id": dataset_id},
        )
        if current != ql_key:
            await storage.delete(ql_key)
    except Exception as e:  # broad: an orphaned image only costs storage
        print(f"  could not clean up {ql_key}: {e}")


async def main() -> None:
    from app.core.config import settings
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage, init_storage
    from app.processing.vector.quicklook import generate_vector_quicklook_with_timeout

    if is_multi_tenant():
        print(
            "ERROR: multi-tenant mode is not supported. Thumbnails would be "
            "generated without a tenant context and written outside each "
            "tenant's storage prefix.",
            file=sys.stderr,
        )
        sys.exit(2)

    force = "--force" in sys.argv
    init_storage()

    engine = create_async_engine(settings.database_url, pool_size=2)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Raw SQL to avoid ORM relationship issues
        where_clause = "" if force else "  AND d.quicklook_256_uri IS NULL"
        result = await db.execute(
            text(
                "SELECT d.id, d.table_name, d.geometry_type, d.quicklook_256_uri "
                "FROM catalog.datasets d "
                "JOIN catalog.records r ON d.record_id = r.id "
                "WHERE r.record_type = 'vector_dataset' "
                "  AND d.table_name IS NOT NULL" + where_clause
            )
        )
        rows = result.fetchall()

        if not rows:
            print("No vector datasets need quicklook generation.")
            return

        label = "to regenerate" if force else "without quicklooks"
        print(f"Found {len(rows)} vector datasets {label}.")
        storage = get_storage()
        success = 0
        skipped = 0

        for i, row in enumerate(rows, 1):
            name = row.table_name or str(row.id)
            ql_key = None
            try:
                ql_bytes = await generate_vector_quicklook_with_timeout(
                    db, row.table_name, row.geometry_type or "", 256, timeout=15.0
                )
                # Check if we got a blank canvas (timeout or no data)
                if len(ql_bytes) < 500:
                    print(f"  [{i}/{len(rows)}] SKIP {name} (blank/timeout)")
                    skipped += 1
                    continue

                # A new key per draw gives the image a new quicklook_version.
                ql_key = f"vectors/{row.id}/quicklook_256_{uuid.uuid4().hex[:12]}.png"
                await storage.put(ql_key, io.BytesIO(ql_bytes))
                # Read under the row lock so cleanup targets the pointer this
                # update replaces, not the one the batch query saw.
                replaced = await db.scalar(
                    text(
                        "SELECT quicklook_256_uri FROM catalog.datasets "
                        "WHERE id = :id FOR NO KEY UPDATE"
                    ),
                    {"id": row.id},
                )
                updated = await db.execute(
                    text(
                        "UPDATE catalog.datasets SET quicklook_256_uri = :uri WHERE id = :id"
                    ),
                    {"uri": ql_key, "id": row.id},
                )
                if not updated.rowcount:
                    await db.rollback()
                    await _drop_unreferenced(db, storage, row.id, ql_key)
                    print(f"  [{i}/{len(rows)}] SKIP {name} (dataset deleted)")
                    skipped += 1
                    continue
                await db.commit()
                if replaced and replaced != ql_key:
                    try:
                        await storage.delete(replaced)
                    except (
                        Exception
                    ) as e:  # broad: an orphaned image only costs storage
                        print(f"  could not remove {replaced}: {e}")
                success += 1
                print(f"  [{i}/{len(rows)}] OK   {name} ({len(ql_bytes)} bytes)")
            except asyncio.CancelledError:
                await asyncio.shield(db.rollback())
                if ql_key is not None:
                    await asyncio.shield(
                        _drop_unreferenced(db, storage, row.id, ql_key)
                    )
                raise
            except Exception as e:
                print(f"  [{i}/{len(rows)}] FAIL {name}: {e}")
                await db.rollback()
                if ql_key is not None:
                    await _drop_unreferenced(db, storage, row.id, ql_key)
                skipped += 1

        try:
            await db.commit()
        except Exception:
            await db.rollback()
        print(f"\nDone: {success} generated, {skipped} skipped.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

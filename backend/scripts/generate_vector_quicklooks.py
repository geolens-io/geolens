"""Bulk-generate vector quicklook thumbnails for existing datasets.

Usage:
    docker compose exec api uv run python scripts/generate_vector_quicklooks.py
    docker compose exec api uv run python scripts/generate_vector_quicklooks.py --force

Without --force: only generates for datasets missing quicklooks.
With --force: regenerates all vector quicklooks (e.g., after renderer changes).
"""

import asyncio
import io
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def main() -> None:
    from app.config import settings
    from app.storage import get_storage, init_storage
    from app.vector.quicklook import generate_vector_quicklook_with_timeout

    force = "--force" in sys.argv
    init_storage()

    engine = create_async_engine(settings.database_url, pool_size=2)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Raw SQL to avoid ORM relationship issues
        where_clause = "" if force else "  AND d.quicklook_256_uri IS NULL"
        result = await db.execute(
            text(
                "SELECT d.id, d.table_name, d.geometry_type "
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
            try:
                ql_bytes = await generate_vector_quicklook_with_timeout(
                    db, row.table_name, row.geometry_type or "", 256, timeout=15.0
                )
                # Check if we got a blank canvas (timeout or no data)
                if len(ql_bytes) < 500:
                    print(f"  [{i}/{len(rows)}] SKIP {name} (blank/timeout)")
                    skipped += 1
                    continue

                ql_key = f"vectors/{row.id}/quicklook_256.png"
                await storage.put(ql_key, io.BytesIO(ql_bytes))
                await db.execute(
                    text(
                        "UPDATE catalog.datasets SET quicklook_256_uri = :uri WHERE id = :id"
                    ),
                    {"uri": ql_key, "id": row.id},
                )
                await db.commit()
                success += 1
                print(f"  [{i}/{len(rows)}] OK   {name} ({len(ql_bytes)} bytes)")
            except Exception as e:
                print(f"  [{i}/{len(rows)}] FAIL {name}: {e}")
                await db.rollback()
                skipped += 1

        try:
            await db.commit()
        except Exception:
            await db.rollback()
        print(f"\nDone: {success} generated, {skipped} skipped.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

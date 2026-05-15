"""Reconcile stale quicklook_256_uri values in catalog.datasets.

Walks every vector dataset row where quicklook_256_uri IS NOT NULL, checks
whether the referenced storage object actually exists via storage.exists(),
and clears the URI on miss.  After the sweep, the existing predicate in
service_records.py (``dataset.quicklook_256_uri is not None``) becomes
truthful — no schema change required.

Usage:
    docker compose exec api uv run python scripts/reconcile_quicklook_uris.py
    docker compose exec api uv run python scripts/reconcile_quicklook_uris.py --dry-run

Operator runbook
----------------

**When to run:**
- After a manifest/seeder re-run where some prior datasets were dropped from
  storage but their DB rows survived (e.g. demo reseeds that overwrite MinIO
  objects without NULLing the URI column first).
- Anytime the search page surfaces ``GET /api/datasets/<id>/quicklook?size=256``
  404 errors in the browser console (the frontend gates that request on
  ``has_quicklook=true`` from the OGC record).

**Dry run first — no DB mutations:**
    docker compose exec api uv run python scripts/reconcile_quicklook_uris.py --dry-run

This prints every stale row it would clear without touching the database.

**Apply — commit the URI clears:**
    docker compose exec api uv run python scripts/reconcile_quicklook_uris.py

Drop ``--dry-run`` to execute the UPDATE statements and commit them.

**Idempotent:**
Re-running the script is safe.  Rows whose URI is already NULL are excluded by
the WHERE clause, so a second run is a no-op (all rows will report KEPT or be
absent from the result set).

**Not a substitute for re-generating thumbnails:**
This script only *clears* stale URIs.  If you want the quicklook PNGs back,
run ``backend/scripts/generate_vector_quicklooks.py`` after reconcile — that
script regenerates thumbnails from the underlying PostGIS table and writes them
to storage, then sets quicklook_256_uri to the new key.

**Scope:**
Only vector datasets (record_type = 'vector_dataset') are swept.  Raster and
VRT records always report has_quicklook=False from service_records.py regardless
of the URI column, so they are excluded from this fix.
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def reconcile(
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Sweep vector datasets with non-null quicklook_256_uri and clear stale ones.

    For each row, calls ``storage.exists(uri)`` once.  On miss, clears the URI
    (unless dry_run=True).  On hit, leaves it untouched.  Storage errors are
    logged but do NOT clear the URI — leaving the URI in place is the safer
    disposition when storage reachability is uncertain.

    Returns:
        (cleared, kept) — counts of rows whose URI was cleared vs. left intact.
    """
    from app.platform.storage import get_storage

    storage = get_storage()

    result = await db.execute(
        text(
            "SELECT d.id, d.quicklook_256_uri "
            "FROM catalog.datasets d "
            "JOIN catalog.records r ON d.record_id = r.id "
            "WHERE r.record_type = 'vector_dataset' "
            "  AND d.quicklook_256_uri IS NOT NULL"
        )
    )
    rows = result.fetchall()

    if not rows:
        print("No vector datasets with non-null quicklook_256_uri found.")
        return (0, 0)

    print(f"Found {len(rows)} vector dataset(s) with quicklook_256_uri set.")

    cleared = 0
    kept = 0

    for i, row in enumerate(rows, 1):
        dataset_id = row.id
        uri = row.quicklook_256_uri
        try:
            exists = await storage.exists(uri)
        except Exception as e:
            # Storage error — leave the URI in place (safer disposition)
            print(f"  [{i}/{len(rows)}] ERROR {dataset_id}: {e}")
            continue

        if exists:
            kept += 1
            # No output for kept rows to keep the log concise
        else:
            print(f"  [{i}/{len(rows)}] STALE {dataset_id} -> {uri}")
            if not dry_run:
                try:
                    await db.execute(
                        text(
                            "UPDATE catalog.datasets SET quicklook_256_uri = NULL WHERE id = :id"
                        ),
                        {"id": dataset_id},
                    )
                    await db.commit()
                except Exception as e:
                    print(f"  [{i}/{len(rows)}] FAIL  {dataset_id} (commit error): {e}")
                    await db.rollback()
                    continue
            cleared += 1

    dry_tag = " (dry-run)" if dry_run else ""
    print(f"Done: {cleared} cleared, {kept} kept{dry_tag}.")
    return (cleared, kept)


async def main() -> None:
    from app.core.config import settings
    from app.platform.storage import init_storage

    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("Running in dry-run mode — no database changes will be committed.")

    init_storage()

    engine = create_async_engine(settings.database_url, pool_size=2)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        await reconcile(db, dry_run=dry_run)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Seed one published public raster dataset in a collection for CI STAC validation.

Run inside the api container (the CI stac-validate job does this):

    docker compose exec -T api uv run --no-dev python /app/backend/scripts/seed_stac_ci.py

Prints ``collection_id=<uuid>`` on success; the CI job feeds it to
stac-api-validator's ``--collection`` flag. Mirrors the ORM factory pattern in
backend/tests/test_stac_visibility.py — no real COG is ingested because the
validator exercises the metadata surface only.
"""

import asyncio
import uuid
from datetime import date


async def main() -> None:
    import app.modules.auth.models  # noqa: F401 -- register catalog.users so the records FK resolves (same pattern as alembic/env.py); the User symbol itself stays unimported per the IDENT-02 layering guard
    from app.core.db import async_session
    from app.modules.catalog.collections.models import Collection, CollectionDataset
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    async with async_session() as session:
        # created_by stays NULL: the record is public+published, so the
        # anonymous visibility filter never consults ownership, and importing
        # the concrete User ORM here would violate the IDENT-02 layering guard.
        record = Record(
            title="STAC CI raster",
            summary="Fixture record for the stac-api-validator CI gate.",
            visibility="public",
            record_status="published",
            record_type="raster_dataset",
            license="CC-BY-4.0",
            spatial_extent=(
                "SRID=4326;POLYGON((-105 39,-104 39,-104 40,-105 40,-105 39))"
            ),
            temporal_start=date(2024, 1, 1),
            temporal_end=date(2024, 12, 31),
        )
        session.add(record)
        await session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=f"ds_{uuid.uuid4().hex[:12]}",
            srid=4326,
            source_format="geotiff",
            source_filename="stac-ci.tif",
        )
        session.add(dataset)
        coll = Collection(
            name="STAC CI Collection",
            description="Fixture collection for the stac-api-validator CI gate.",
        )
        session.add(coll)
        await session.flush()
        session.add(CollectionDataset(collection_id=coll.id, dataset_id=dataset.id))
        await session.commit()
        print(f"collection_id={coll.id}")


if __name__ == "__main__":
    asyncio.run(main())

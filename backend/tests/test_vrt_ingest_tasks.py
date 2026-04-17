import uuid

from sqlalchemy import select

from app.modules.auth.models import User
from app.core.config import settings
from app.processing.ingest.tasks import create_vrt_dataset


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


class TestCreateVrtDataset:
    async def test_public_vrt_records_start_published(self, test_db_session):
        admin_id = await _get_admin_id(test_db_session)

        record, dataset, raster_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "epsg": 4326,
                "band_count": 1,
                "dtype": "uint8",
                "width": 256,
                "height": 256,
            },
            asset_sha256="a" * 64,
            vrt_size=512,
            source_filename="public-mosaic.vrt",
            created_by=admin_id,
            title=f"Public VRT {uuid.uuid4().hex[:6]}",
            summary="Regression test for public VRT visibility",
            visibility="public",
            vrt_type="mosaic",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )

        await test_db_session.commit()
        await test_db_session.refresh(record)
        await test_db_session.refresh(dataset)
        await test_db_session.refresh(raster_asset)

        assert record.record_type == "vrt_dataset"
        assert record.visibility == "public"
        assert record.record_status == "published"
        assert dataset.record_id == record.id
        assert raster_asset.dataset_id == dataset.id

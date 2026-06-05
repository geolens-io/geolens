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

    async def test_vrt_mosaic_of_dem_tiles_is_flagged_is_dem(self, test_db_session):
        """A VRT mosaic of single-band float DEM tiles must itself be flagged
        as a DEM, so map terrain + hillshade can use it (#185). Without this the
        mosaic lands is_dem=false and is unusable as a terrain source."""
        admin_id = await _get_admin_id(test_db_session)

        _, _, raster_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "epsg": 2056,
                "band_count": 1,
                "dtype": "float32",
                "width": 256,
                "height": 256,
                "is_dem_candidate": True,
            },
            asset_sha256="b" * 64,
            vrt_size=512,
            source_filename="dem-mosaic.vrt",
            created_by=admin_id,
            title=f"DEM VRT {uuid.uuid4().hex[:6]}",
            summary="is_dem propagation",
            visibility="public",
            vrt_type="mosaic",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )

        await test_db_session.commit()
        await test_db_session.refresh(raster_asset)
        assert raster_asset.is_dem is True

    async def test_vrt_not_flagged_is_dem_when_multiband(self, test_db_session):
        """A multi-band (band-stack) VRT is not a DEM."""
        admin_id = await _get_admin_id(test_db_session)

        _, _, raster_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "epsg": 4326,
                "band_count": 3,
                "dtype": "uint8",
                "width": 256,
                "height": 256,
                "is_dem_candidate": False,
            },
            asset_sha256="c" * 64,
            vrt_size=512,
            source_filename="rgb-stack.vrt",
            created_by=admin_id,
            title=f"RGB VRT {uuid.uuid4().hex[:6]}",
            summary="is_dem negative case",
            visibility="public",
            vrt_type="band_stack",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )

        await test_db_session.commit()
        await test_db_session.refresh(raster_asset)
        assert raster_asset.is_dem is False

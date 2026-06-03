"""Tests for ensure_geom_column geometry column normalization."""

import pytest
from sqlalchemy import text


class TestEnsureGeomColumn:
    """Test the ensure_geom_column safety net for geometry column naming."""

    @pytest.fixture(autouse=True)
    async def setup_table(self, test_db_session):
        """Create a test table with a non-standard geometry column name."""
        self.session = test_db_session
        self.table_name = "test_geom_rename"
        await self.session.execute(
            text(f"DROP TABLE IF EXISTS data.{self.table_name} CASCADE")
        )
        await self.session.commit()
        yield
        await self.session.execute(
            text(f"DROP TABLE IF EXISTS data.{self.table_name} CASCADE")
        )
        await self.session.commit()

    async def test_renames_wkb_geometry_to_geom(self):
        """When geometry column is 'wkb_geometry', rename to 'geom'."""
        from app.processing.ingest.metadata import ensure_geom_column

        await self.session.execute(
            text(
                f"CREATE TABLE data.{self.table_name} ("
                "  gid serial PRIMARY KEY,"
                "  wkb_geometry geometry(Point, 4326)"
                ")"
            )
        )
        await self.session.commit()

        await ensure_geom_column(self.session, self.table_name)

        result = await self.session.execute(
            text(
                "SELECT f_geometry_column FROM geometry_columns "
                "WHERE f_table_schema = 'data' AND f_table_name = :t"
            ),
            {"t": self.table_name},
        )
        assert result.scalar_one() == "geom"

    async def test_noop_when_already_geom(self):
        """When geometry column is already 'geom', do nothing."""
        from app.processing.ingest.metadata import ensure_geom_column

        await self.session.execute(
            text(
                f"CREATE TABLE data.{self.table_name} ("
                "  gid serial PRIMARY KEY,"
                "  geom geometry(Point, 4326)"
                ")"
            )
        )
        await self.session.commit()

        await ensure_geom_column(self.session, self.table_name)

        result = await self.session.execute(
            text(
                "SELECT f_geometry_column FROM geometry_columns "
                "WHERE f_table_schema = 'data' AND f_table_name = :t"
            ),
            {"t": self.table_name},
        )
        assert result.scalar_one() == "geom"

    async def test_noop_for_non_spatial_table(self):
        """When table has no geometry column, do nothing (no error)."""
        from app.processing.ingest.metadata import ensure_geom_column

        await self.session.execute(
            text(
                f"CREATE TABLE data.{self.table_name} ("
                "  gid serial PRIMARY KEY,"
                "  name text"
                ")"
            )
        )
        await self.session.commit()

        # Should not raise
        await ensure_geom_column(self.session, self.table_name)

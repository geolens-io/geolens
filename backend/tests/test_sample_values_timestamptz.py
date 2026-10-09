"""Sampled timestamptz values match the text vector tiles write."""

import uuid

import pytest
from sqlalchemy import text

from app.platform.timestamptz_text import utc_timestamptz_text
from app.processing.ingest.metadata import get_column_info, get_sample_values

pytestmark = pytest.mark.anyio


async def test_timestamptz_samples_use_the_tile_text_in_any_session_zone(
    test_db_session,
):
    table = f"tst_tstz_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, at timestamptz)")
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (at) VALUES "
            "('2024-03-01 12:00:00-05'), ('2024-07-01 12:00:00.25+02')"
        )
    )
    await test_db_session.commit()
    try:
        await test_db_session.execute(text("SET TIME ZONE 'America/New_York'"))
        cols = await get_column_info(test_db_session, table)
        samples = await get_sample_values(test_db_session, table, cols)
        expected = (
            await test_db_session.execute(
                text(f"SELECT {utc_timestamptz_text('at')} FROM data.{table}")
            )
        ).scalars()
        assert sorted(samples["at"]) == sorted(expected)
        assert "2024-03-01T17:00:00+00:00" in samples["at"]
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(text("RESET TIME ZONE"))
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ingest.metadata import (
    _parse_box3d_z_bounds,
    detect_3d_metadata,
    promote_z_to_elev,
)


def test_parse_box3d_z_bounds_extracts_numeric_range():
    assert _parse_box3d_z_bounds("BOX3D(1 2 -5.5,4 6 8.25)") == (-5.5, 8.25)


def test_parse_box3d_z_bounds_returns_none_for_invalid_text():
    assert _parse_box3d_z_bounds(None) == (None, None)
    assert _parse_box3d_z_bounds("BOX(1 2,3 4)") == (None, None)


@pytest.mark.asyncio
async def test_detect_3d_metadata_uses_3d_extent_and_parses_z_bounds():
    session = AsyncMock()

    has_geom_result = Mock()
    has_geom_result.scalar_one.return_value = True

    metadata_result = Mock()
    metadata_result.one_or_none.return_value = SimpleNamespace(
        n_dims=3,
        extent_3d="BOX3D(1 2 -12.5,4 6 77.25)",
    )

    session.execute.side_effect = [has_geom_result, metadata_result]

    result = await detect_3d_metadata(session, "sample_table")

    assert result == {
        "is_3d": True,
        "n_dims": 3,
        "z_min": -12.5,
        "z_max": 77.25,
    }

    metadata_query = str(session.execute.await_args_list[1].args[0])
    assert "ST_3DExtent" in metadata_query
    assert "ST_Is3D" not in metadata_query


@pytest.mark.asyncio
async def test_detect_3d_metadata_returns_2d_defaults_without_extent():
    session = AsyncMock()

    has_geom_result = Mock()
    has_geom_result.scalar_one.return_value = True

    metadata_result = Mock()
    metadata_result.one_or_none.return_value = SimpleNamespace(
        n_dims=2,
        extent_3d=None,
    )

    session.execute.side_effect = [has_geom_result, metadata_result]

    result = await detect_3d_metadata(session, "sample_table")

    assert result == {
        "is_3d": False,
        "n_dims": 2,
        "z_min": None,
        "z_max": None,
    }


@pytest.mark.asyncio
async def test_promote_z_to_elev_filters_on_ndims_instead_of_st_is3d():
    session = AsyncMock()

    column_check_result = Mock()
    column_check_result.scalar_one_or_none.return_value = None

    session.execute.side_effect = [
        column_check_result,
        Mock(),
        Mock(),
    ]

    promoted = await promote_z_to_elev(session, "sample_table", "Point")

    assert promoted is True

    update_query = str(session.execute.await_args_list[2].args[0])
    assert "ST_NDims(geom) > 2" in update_query
    assert "ST_Is3D" not in update_query

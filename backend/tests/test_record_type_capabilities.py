"""The record-type capability table, and the closed answer for unknown types."""

import re

import pytest

from app.core.record_types import RECORD_TYPES, RecordTypeCapabilities, capabilities
from app.modules.catalog.datasets.domain.models import Record

_VECTOR = RecordTypeCapabilities(
    feature_table=True,
    map_layer_type="vector_geolens",
    tile_token="vector",
    ogc_item_type="feature",
)
_RASTER = RecordTypeCapabilities(
    feature_table=False,
    map_layer_type="raster_geolens",
    tile_token="raster",
    ogc_item_type="coverage",
)
_NONE = RecordTypeCapabilities(
    feature_table=False, map_layer_type=None, tile_token=None, ogc_item_type=None
)


@pytest.mark.parametrize(
    ("record_type", "expected"),
    [
        ("vector_dataset", _VECTOR),
        ("table", _VECTOR),
        ("raster_dataset", _RASTER),
        ("vrt_dataset", _RASTER),
        ("map", _VECTOR),
        ("service", _VECTOR),
        ("collection", _VECTOR),
        ("point_cloud_dataset", _NONE),
        (None, _NONE),
    ],
)
def test_each_record_type_answers_every_capability(
    record_type: str | None, expected: RecordTypeCapabilities
) -> None:
    """Known types keep today's answers; an unknown or missing type gets none."""
    assert capabilities(record_type) == expected


def test_the_table_covers_exactly_the_checked_vocabulary() -> None:
    """RECORD_TYPES matches the values chk_records_record_type admits."""
    constraint = next(
        c for c in Record.__table__.constraints if c.name == "chk_records_record_type"
    )
    admitted = set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))
    assert admitted == set(RECORD_TYPES)

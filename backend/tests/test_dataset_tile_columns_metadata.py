from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.catalog.datasets.domain.schemas import DatasetMeta


def test_dataset_meta_accepts_tile_columns_allowlist() -> None:
    meta = DatasetMeta(tile_columns=["mag", "depth_km"])

    assert meta.tile_columns == ["mag", "depth_km"]


def test_dataset_meta_rejects_duplicate_tile_columns() -> None:
    with pytest.raises(ValidationError, match="tile_columns entries must be unique"):
        DatasetMeta(tile_columns=["mag", "mag"])


def test_dataset_meta_rejects_invalid_tile_column_names() -> None:
    with pytest.raises(ValidationError, match="Invalid tile column names"):
        DatasetMeta(tile_columns=["mag", "drop table"])

"""Unit tests for the export selection, cap, artifact-choice and range-policy functions."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.processing.export import selection
from app.processing.export.artifact_cache import ExportArtifact, strong_etag
from app.processing.export.schemas import ExportFormat

_DATASET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_KEY = "url/version"


def _artifact(*, digest: str = "abc", size: int = 1000, contested: bool = False):
    return ExportArtifact(
        key="k",
        digest=digest,
        size=size,
        built_at=0.0,
        filename="f.geojson",
        media_type="application/geo+json",
        contested=contested,
    )


def _dataset(**overrides):
    fields = {
        "feature_count": 10,
        "table_name": "t_points",
        "column_info": [{"name": "pop", "type": "integer"}],
        "geometry_type": "Point",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class _RecordingDb:
    """Captures the statement a count runs and answers it with ``count``."""

    def __init__(self, count: int = 0) -> None:
        self.count = count
        self.statements: list = []

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalar_one=lambda: self.count)


@pytest.mark.parametrize(
    ("xy", "format", "geometry_type", "columns", "expected"),
    [
        (True, ExportFormat.csv, "Point", [], True),
        (True, ExportFormat.csv, "multipoint", None, True),
        (False, ExportFormat.csv, "Point", [], False),
        (True, ExportFormat.geojson, "Point", [], False),
        (True, ExportFormat.csv, "Polygon", [], False),
        (True, ExportFormat.csv, None, [], False),
        (True, ExportFormat.csv, "Point", [{"name": "Longitude"}], False),
        (True, ExportFormat.csv, "Point", ["latitude", {"name": "pop"}], True),
    ],
)
def test_wants_xy(xy, format, geometry_type, columns, expected):
    """Coordinate columns only for CSV of a point layer that has neither column."""
    assert selection.wants_xy(xy, format, geometry_type, columns) is expected


@pytest.mark.parametrize(
    ("range_header", "if_range", "expected"),
    [
        ("bytes=0-99", None, (0, 99)),
        ("bytes=100-", None, (100, 999)),
        ("bytes=0-99", '"abc"', None),
        ("bytes=0-1,5-9", None, None),
        ("items=0-1", None, None),
        (None, None, None),
    ],
)
def test_bare_satisfiable_range(range_header, if_range, expected):
    """Only a single satisfiable Range with no If-Range resolves to a slice."""
    assert selection.bare_satisfiable_range(range_header, if_range, 1000) == expected


def test_built_etag_prefers_the_published_artifact():
    """The published artifact's validator wins, then the local digest, else none."""
    assert selection.built_etag(_artifact(digest="pub"), "local") == strong_etag("pub")
    assert selection.built_etag(None, "local") == strong_etag("local")
    assert selection.built_etag(None, None) is None


@pytest.mark.anyio
async def test_cached_range_allowed(monkeypatch):
    """A hit slices unless contested or the URL answered other bytes recently."""
    calls: list[str] = []
    answered_other = {"value": False}

    async def _other(dataset_id, key, digest):
        calls.append(digest)
        return answered_other["value"]

    monkeypatch.setattr(
        selection.artifact_cache, "url_answered_other_bytes_recently", _other
    )
    kwargs = {"dataset_id": _DATASET_ID, "selection": _KEY, "if_range": None}

    assert not await selection.cached_range_allowed(
        _artifact(contested=True), range_header="bytes=0-9", **kwargs
    )
    assert await selection.cached_range_allowed(
        _artifact(), range_header=None, **kwargs
    )
    assert calls == [], "no URL-history read without a bare satisfiable Range"

    assert await selection.cached_range_allowed(
        _artifact(), range_header="bytes=0-9", **kwargs
    )
    answered_other["value"] = True
    assert not await selection.cached_range_allowed(
        _artifact(), range_header="bytes=0-9", **kwargs
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("contested", "range_header", "follow_key", "held", "only_these", "other", "want"),
    [
        (True, "bytes=0-9", True, True, True, False, (False, False)),
        (False, None, True, True, True, False, (False, False)),
        (False, "bytes=10-19", True, True, True, False, (True, False)),
        (False, "bytes=10-19", False, True, True, False, (False, False)),
        (False, "bytes=10-19", True, False, True, False, (False, False)),
        (False, "bytes=10-19", True, True, False, False, (False, False)),
        (False, "bytes=0-9", False, True, True, False, (False, True)),
        (False, "bytes=0-9", False, True, True, True, (False, False)),
    ],
)
async def test_built_range_policy(
    monkeypatch, contested, range_header, follow_key, held, only_these, other, want
):
    """A fresh build slices only bytes the key pins, or byte 0 on a quiet URL."""

    async def _only_these(dataset_id, key, digest):
        return only_these

    async def _other(dataset_id, key, digest):
        return other

    monkeypatch.setattr(
        selection.artifact_cache, "url_held_only_these_bytes", _only_these
    )
    monkeypatch.setattr(
        selection.artifact_cache, "url_answered_other_bytes_recently", _other
    )
    stored = _artifact(digest="d1", contested=contested)
    got = await selection.built_range_policy(
        stored,
        dataset_id=_DATASET_ID,
        selection=_KEY,
        bytes_follow_key=follow_key,
        held_before_build={"d1"} if held else set(),
        range_header=range_header,
        if_range=None,
    )
    assert got == want


@pytest.mark.anyio
async def test_count_escapes_colons_and_binds_an_ordinary_bbox(monkeypatch):
    """The count splices the canonical filter with colons escaped and binds the envelope."""
    monkeypatch.setattr(selection, "_MAX_EXPORT_FEATURES", 7)
    db = _RecordingDb(count=3)
    got = await selection._count_selected_features(
        db,
        table_name="t_points",
        where="ts = '2024-01-01T00:00:00'",
        column_info=[{"name": "ts", "type": "text"}],
        bbox=[0.0, 1.0, 2.0, 3.0],
        has_geometry=True,
        schema="data",
    )
    assert got == 3
    (statement,) = db.statements
    sql = statement.text
    assert "'2024-01-01T00\\:00\\:00'" in sql
    assert "geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)" in sql
    assert sql.endswith("LIMIT :limit) sub")
    bound = {k: v.value for k, v in statement._bindparams.items()}
    assert bound == {"limit": 8, "minx": 0.0, "miny": 1.0, "maxx": 2.0, "maxy": 3.0}


@pytest.mark.anyio
async def test_count_ignores_bbox_without_geometry_and_rejects_a_bad_filter():
    """No geometry means no spatial clause; an unknown column is a ValueError."""
    db = _RecordingDb()
    await selection._count_selected_features(
        db,
        table_name="t_rows",
        where=None,
        column_info=None,
        bbox=[0.0, 0.0, 1.0, 1.0],
        has_geometry=False,
        schema="data",
    )
    assert "WHERE TRUE LIMIT" in db.statements[0].text

    with pytest.raises(ValueError):
        await selection._count_selected_features(
            _RecordingDb(),
            table_name="t_rows",
            where="nope > 1",
            column_info=[{"name": "pop", "type": "integer"}],
            bbox=None,
            has_geometry=False,
            schema="data",
        )


@pytest.mark.anyio
async def test_check_selection_enforces_the_cap(monkeypatch):
    """Over the cap: unfiltered is refused outright, filtered is refused on its count."""
    monkeypatch.setattr(selection, "_MAX_EXPORT_FEATURES", 5)
    counted: list[int] = []
    count_result = {"value": 5}

    async def _count(db, **kwargs):
        counted.append(1)
        return count_result["value"]

    monkeypatch.setattr(selection, "_count_selected_features", _count)
    common = {"format": ExportFormat.geojson, "schema": "data"}

    assert (
        await selection.check_selection(
            None, _dataset(feature_count=5), bbox=None, where=None, **common
        )
        is None
    )
    assert (
        await selection.check_selection(
            None, _dataset(feature_count=None), bbox=None, where=None, **common
        )
        is None
    )
    assert counted == [], "a dataset at or under the cap is not counted"

    with pytest.raises(selection.SelectionTooLargeError, match="unfiltered-export"):
        await selection.check_selection(
            None, _dataset(feature_count=6), bbox=None, where=None, **common
        )
    assert counted == []

    assert (
        await selection.check_selection(
            None, _dataset(feature_count=6), bbox=None, where="pop > 1", **common
        )
        is None
    )
    count_result["value"] = 6
    with pytest.raises(selection.SelectionTooLargeError, match="still selects more"):
        await selection.check_selection(
            None, _dataset(feature_count=6), bbox=[0, 0, 1, 1], where=None, **common
        )
    assert len(counted) == 2


@pytest.mark.anyio
async def test_check_selection_validates_the_filter_for_ogr_formats():
    """An ogr2ogr export's filter is checked against column_info before HEAD answers."""
    with pytest.raises(ValueError):
        await selection.check_selection(
            None,
            _dataset(),
            format=ExportFormat.csv,
            bbox=None,
            where="missing = 1",
            schema="data",
        )


@pytest.mark.anyio
async def test_check_selection_maps_the_parquet_cap(monkeypatch):
    """The parquet planner's over-cap error surfaces as SelectionTooLargeError, untouched."""
    from app.processing.export import parquet

    async def _plan(db, table_name, **kwargs):
        raise parquet.ExportTooLargeError("too many rows")

    async def _never(*args, **kwargs):
        raise AssertionError("parquet owns its count")

    monkeypatch.setattr(parquet, "plan_parquet_export", _plan)
    monkeypatch.setattr(selection, "_count_selected_features", _never)
    with pytest.raises(selection.SelectionTooLargeError, match="^too many rows$"):
        await selection.check_selection(
            None,
            _dataset(feature_count=10**9),
            format=ExportFormat.parquet,
            bbox=None,
            where=None,
            schema="data",
        )


@pytest.mark.parametrize(
    ("where", "has_gid", "plan", "source_format", "expected"),
    [
        (None, True, True, "geojson", True),
        ("pop > 1", True, True, "geojson", False),
        (None, False, True, "geojson", False),
        (None, True, False, "geojson", False),
        (None, True, True, None, False),
    ],
)
def test_bytes_follow_key(where, has_gid, plan, source_format, expected):
    """Only an unfiltered parquet export of a GeoLens-owned table with gid is key-pinned."""
    dataset = SimpleNamespace(
        source_format=source_format,
        record=SimpleNamespace(record_type="vector_dataset"),
        origin_ref=None,
    )
    parquet_plan = SimpleNamespace(has_gid=has_gid) if plan else None
    assert (
        selection.bytes_follow_key(dataset, where=where, parquet_plan=parquet_plan)
        is expected
    )

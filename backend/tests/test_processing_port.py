"""Unit test for the ProcessingPort seam (Phase 225 D-27 / PROCESS-03).

Constructs a minimal FakeProcessingPort with canned return values and
passes it to a service-layer function in app/processing/ai/service.py
(per D-15 — the function takes `port: ProcessingPort` as keyword-only)
to verify the seam is genuinely testable in isolation without a database
or LLM.

Maps to Phase 225 ROADMAP SC#5: "AI features consume catalog data exclusively
through the Protocol — verifiable by ... a focused unit test that swaps
in a fake ProcessingPort."
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakeProcessingPort:
    """Minimal stub implementing the ProcessingPort surface with canned returns.

    All async methods use async def; sync methods use def. All return canned
    values — no real database I/O. Structurally satisfies ProcessingPort
    (PEP 544 structural subtyping).
    """

    def __init__(self):
        _dataset_id = uuid.uuid4()
        self._dataset = MagicMock()
        self._dataset.id = _dataset_id
        self._dataset.table_name = "test_dataset_table"
        self._dataset.geometry_type = "Polygon"
        self._dataset.feature_count = 100
        self._dataset.srid = 4326
        self._dataset.original_srid = 4326
        self._dataset.source_format = "GeoJSON"
        self._dataset.source_filename = "test.geojson"
        self._dataset.source_url = None
        self._dataset.column_info = [{"name": "area", "type": "float"}]
        self._dataset.sample_values = {"area": [1.0, 2.0, 3.0]}
        self._dataset.quality_detail = None
        self._dataset.quality_statement = None
        self._dataset.current_version = 1
        self._dataset.is_3d = False
        self._dataset.record_id = uuid.uuid4()
        self._dataset.attributes = []

        self._dataset.record = MagicMock()
        self._dataset.record.id = uuid.uuid4()
        self._dataset.record.title = "Test Dataset"
        self._dataset.record.summary = "A test dataset for unit tests"
        self._dataset.record.keywords = []
        self._dataset.record.spatial_extent = None
        self._dataset.record.lineage_summary = None
        self._dataset.record.source_organization = None
        self._dataset.record.access_constraints = None
        self._dataset.record.temporal_start = None
        self._dataset.record.temporal_end = None
        self._dataset.record.record_type = "dataset"
        self._dataset.record.created_at = None

        self._map = MagicMock()
        self._map.id = uuid.uuid4()
        self._map.name = "Test Map"
        self._map.created_by = None
        self._map.basemap_style = "default"

        self._dataset_id = str(_dataset_id)

    # -------------------------------------------------------------------------
    # Read-side
    # -------------------------------------------------------------------------

    async def search_datasets(self, session, user, user_roles, filters):
        return ([self._dataset], 1)

    def apply_visibility_filter(
        self, stmt, user, user_roles, record_cls, grant_cls=None
    ):
        return stmt  # No-op: returns stmt unmodified

    async def check_dataset_access(
        self, session, dataset, dataset_id, user, *, user_roles=None
    ):
        return user_roles or set()

    async def get_user_roles(self, session, user):
        return {"viewer"}

    async def get_dataset(self, session, dataset_id):
        if str(dataset_id) == self._dataset_id:
            return self._dataset
        return None

    async def get_record(self, session, record_id):
        return self._dataset.record

    async def get_column_stats(
        self,
        session,
        table_name,
        column_name,
        *,
        class_count=5,
        allowed_tables=None,
    ):
        return {
            "min": 0.0,
            "max": 100.0,
            "count": 100,
            "mean": 50.0,
            "quantiles": [25.0, 50.0, 75.0],
        }

    async def get_distinct_values(
        self, session, table_name, column_name, limit=100, *, allowed_tables=None
    ):
        return ["A", "B", "C"]

    def extract_bbox(self, dataset):
        return [-74.0, 40.7, -73.9, 40.8]

    # -------------------------------------------------------------------------
    # OQ-3 InstrumentedAttribute encapsulators
    # -------------------------------------------------------------------------

    async def get_records_without_embeddings(self, session, *, force=False):
        return [self._dataset.record]

    async def get_datasets_meta_by_ids(self, session, ids):
        return [
            (
                self._dataset.id,
                self._dataset.table_name,
                self._dataset.geometry_type,
            )
        ]

    async def get_catalog_vocabulary(self, session):
        return ["test", "vocabulary", "keyword"]

    async def get_keywords_for_records(self, session, record_ids):
        if not record_ids:
            return []
        return ["related", "keywords"]

    async def get_record_keyword_count(self, session, record_id):
        return 0

    async def get_attribute_metadata(self, session, dataset_id):
        return []

    async def get_dataset_version(self, session, dataset_id):
        return None

    # -------------------------------------------------------------------------
    # Write-side
    # -------------------------------------------------------------------------

    async def create_dataset(
        self,
        session,
        table_name,
        title,
        created_by,
        *,
        summary=None,
        visibility="private",
        ingestion=None,
    ):
        return self._dataset

    async def create_map(self, session, name, description, created_by, notes=None):
        self._map.name = name
        return self._map

    async def update_map(self, session, map_id, **kwargs):
        return (self._map, [], None, None)

    def create_ingestion_result(self, **kwargs):
        result = MagicMock()
        for k, v in kwargs.items():
            setattr(result, k, v)
        return result

    # -------------------------------------------------------------------------
    # Source preview helper
    # -------------------------------------------------------------------------

    def build_gdal_source(
        self,
        service_type,
        base_url,
        layer_name,
        layer_id=None,
        token=None,
        order_field=None,
        result_limit=None,
    ):
        return (f"{service_type}:{base_url}", layer_name)

    # -------------------------------------------------------------------------
    # ORM class helpers (Plans 02 + 03a/03b)
    # -------------------------------------------------------------------------

    def get_record_orm_class(self):
        return MagicMock  # Stand-in — tests don't construct real SQL with it

    def get_grant_orm_class(self):
        return MagicMock

    def get_dataset_orm_class(self):
        return MagicMock

    def get_dataset_version_orm_class(self):
        return MagicMock

    def get_record_distribution_orm_class(self):
        return MagicMock

    def get_attribute_metadata_orm_class(self):
        return MagicMock

    # -------------------------------------------------------------------------
    # Dataset-with-attributes loader (Plan 02)
    # -------------------------------------------------------------------------

    async def get_dataset_with_attributes(self, session, dataset_id):
        if str(dataset_id) == self._dataset_id:
            return self._dataset
        return None


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
async def test_fake_processing_port_satisfies_protocol() -> None:
    """Verify FakeProcessingPort structurally satisfies ProcessingPort.

    Uses isinstance() on the @runtime_checkable Protocol. This proves
    FakeProcessingPort can stand in for DefaultProcessingPort in tests
    (D-27 / SC#5 structural check).

    runtime_checkable on a Protocol only verifies attribute PRESENCE, not
    method signatures (PEP 544). The signature spot-checks below catch the
    most common drift forms — a renamed/dropped parameter on a Port method
    that callers actually rely on.
    """
    import inspect

    from app.core.processing_port import ProcessingPort

    port = FakeProcessingPort()
    assert isinstance(port, ProcessingPort), (
        "FakeProcessingPort does not satisfy ProcessingPort Protocol — "
        "a method required by ProcessingPort is missing or has the wrong signature."
    )

    # Signature spot-checks for the most fragile / call-site-sensitive methods.
    # runtime_checkable doesn't verify these; do it explicitly.
    sig = inspect.signature(port.get_distinct_values)
    assert "limit" in sig.parameters, (
        "get_distinct_values lost its limit parameter — call sites in "
        "ai/service.py and chat_service.py rely on it"
    )
    assert "allowed_tables" in sig.parameters, (
        "get_distinct_values lost its allowed_tables kwarg"
    )

    sig = inspect.signature(port.get_dataset_with_attributes)
    assert "dataset_id" in sig.parameters, (
        "get_dataset_with_attributes lost its dataset_id parameter — "
        "metadata_service._build_dataset_context relies on it"
    )

    sig = inspect.signature(port.get_keywords_for_records)
    assert "record_ids" in sig.parameters, (
        "get_keywords_for_records lost its record_ids parameter — "
        "metadata_service._get_related_keywords_from_embeddings relies on it"
    )

    sig = inspect.signature(port.get_column_stats)
    assert "class_count" in sig.parameters, (
        "get_column_stats lost its class_count kwarg"
    )

    # Exercise read methods to confirm canned returns work
    fake_session = AsyncMock()
    datasets, count = await port.search_datasets(
        fake_session, None, {"viewer"}, MagicMock()
    )
    assert count == 1
    assert datasets[0].id == uuid.UUID(port._dataset_id)

    bbox = port.extract_bbox(datasets[0])
    assert bbox == [-74.0, 40.7, -73.9, 40.8]


@pytest.mark.asyncio
async def test_processing_port_seam_search_tool() -> None:
    """Verify _execute_search_tool runs through FakeProcessingPort without a database.

    Demonstrates the D-15 seam: the AI service function receives `port` via
    keyword-only parameter and invokes port.search_datasets + port.extract_bbox
    entirely without a real database or LLM call.

    This closes Phase 225 ROADMAP SC#5: "AI features consume catalog data
    exclusively through the Protocol — verifiable by ... a focused unit test
    that swaps in a fake ProcessingPort."
    """
    from app.processing.ai.service import _execute_search_tool

    port = FakeProcessingPort()
    fake_session = AsyncMock()
    fake_user = MagicMock(id=uuid.uuid4(), username="test_user")

    results = await _execute_search_tool(
        fake_session,
        fake_user,
        {"viewer"},
        {"q": "polygon datasets", "limit": 5},
        port=port,
    )

    # FakeProcessingPort.search_datasets returns ([self._dataset], 1)
    assert isinstance(results, list), "Expected a list of dataset dicts"
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"

    result = results[0]
    assert result["id"] == port._dataset_id
    assert result["title"] == "Test Dataset"
    assert result["geometry_type"] == "Polygon"
    # extract_bbox canned return [-74.0, 40.7, -73.9, 40.8]
    assert result["extent_bbox"] == [-74.0, 40.7, -73.9, 40.8]

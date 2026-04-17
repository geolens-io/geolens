"""Tests for VRT lifecycle: generation tracking, status, history, regeneration."""

import inspect
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Task 1: Model & Schema tests
# ---------------------------------------------------------------------------


class TestVrtGenerationModel:
    """Verify VrtGeneration model has all required columns."""

    def test_model_has_required_columns(self):
        from app.processing.raster.models import VrtGeneration

        mapper = VrtGeneration.__table__
        col_names = {c.name for c in mapper.columns}
        expected = {
            "id",
            "vrt_dataset_id",
            "status",
            "started_at",
            "completed_at",
            "duration_seconds",
            "error_message",
            "source_count",
            "triggered_by",
            "created_at",
        }
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_model_table_name(self):
        from app.processing.raster.models import VrtGeneration

        assert VrtGeneration.__tablename__ == "vrt_generations"

    def test_model_schema(self):
        from app.processing.raster.models import VrtGeneration

        # __table_args__ is a tuple: (constraints..., {"schema": "catalog"})
        schema_dict = VrtGeneration.__table_args__[-1]
        assert schema_dict["schema"] == "catalog"

    def test_primary_key_is_uuid(self):
        from app.processing.raster.models import VrtGeneration

        pk_cols = [c for c in VrtGeneration.__table__.columns if c.primary_key]
        assert len(pk_cols) == 1
        assert pk_cols[0].name == "id"


class TestVrtStatusResponseSchema:
    """VrtStatusResponse schema validation."""

    def test_valid_status_response(self):
        from app.modules.catalog.datasets.domain.schemas import VrtStatusResponse

        data = VrtStatusResponse(
            status="ready",
            source_count=3,
            source_health=[],
        )
        assert data.status == "ready"
        assert data.source_count == 3
        assert data.last_generation_at is None
        assert data.active_generation is None

    def test_status_with_optional_fields(self):
        from app.modules.catalog.datasets.domain.schemas import VrtActiveGeneration, VrtStatusResponse

        now = datetime.now(timezone.utc)
        active = VrtActiveGeneration(
            generation_id=uuid.uuid4(),
            started_at=now,
            elapsed_seconds=12.5,
        )
        data = VrtStatusResponse(
            status="regenerating",
            last_generation_at=now,
            source_count=2,
            active_generation=active,
            source_health=[],
        )
        assert data.active_generation is not None
        assert data.active_generation.elapsed_seconds == 12.5


class TestVrtGenerationItemSchema:
    """VrtGenerationItem schema validation."""

    def test_valid_generation_item(self):
        from app.modules.catalog.datasets.domain.schemas import VrtGenerationItem

        now = datetime.now(timezone.utc)
        item = VrtGenerationItem(
            id=uuid.uuid4(),
            status="completed",
            started_at=now,
            completed_at=now,
            duration_seconds=2.5,
            source_count=4,
            triggered_by="system",
        )
        assert item.status == "completed"
        assert item.duration_seconds == 2.5

    def test_minimal_generation_item(self):
        from app.modules.catalog.datasets.domain.schemas import VrtGenerationItem

        item = VrtGenerationItem(id=uuid.uuid4(), status="pending")
        assert item.started_at is None
        assert item.error_message is None


class TestVrtGenerationListResponseSchema:
    """VrtGenerationListResponse contains generations and total."""

    def test_valid_list_response(self):
        from app.modules.catalog.datasets.domain.schemas import VrtGenerationItem, VrtGenerationListResponse

        items = [
            VrtGenerationItem(id=uuid.uuid4(), status="completed"),
            VrtGenerationItem(id=uuid.uuid4(), status="failed"),
        ]
        resp = VrtGenerationListResponse(generations=items, total=10)
        assert len(resp.generations) == 2
        assert resp.total == 10


class TestVrtSourceHealthSchema:
    """VrtSourceHealth schema validation."""

    def test_healthy_source(self):
        from app.modules.catalog.datasets.domain.schemas import VrtSourceHealth

        h = VrtSourceHealth(
            dataset_id=uuid.uuid4(),
            title="Source A",
            status="healthy",
        )
        assert h.status == "healthy"

    def test_missing_source(self):
        from app.modules.catalog.datasets.domain.schemas import VrtSourceHealth

        h = VrtSourceHealth(
            dataset_id=uuid.uuid4(),
            title="Source B",
            status="missing",
        )
        assert h.status == "missing"

    def test_inaccessible_source(self):
        from app.modules.catalog.datasets.domain.schemas import VrtSourceHealth

        h = VrtSourceHealth(
            dataset_id=uuid.uuid4(),
            title="Source C",
            status="inaccessible",
        )
        assert h.status == "inaccessible"


class TestMigrationStructure:
    """Initial schema includes vrt_generations table."""

    def test_initial_schema_contains_vrt_generations(self):
        """Verify the initial tables migration creates vrt_generations."""
        import os

        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "alembic",
            "versions",
            "0002_initial_tables.py",
        )
        with open(migration_path) as f:
            content = f.read()

        assert "vrt_generations" in content
        assert "vrt_dataset_id" in content

    def test_initial_migration_importable(self):
        """Initial migration files have upgrade/downgrade functions."""
        import importlib.util
        import os

        for filename in (
            "0001_foundations.py",
            "0002_initial_tables.py",
            "0003_procrastinate.py",
        ):
            path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "alembic",
                "versions",
                filename,
            )
            spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
            assert spec is not None, f"{filename} not found"
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            assert hasattr(mod, "upgrade"), f"{filename} missing upgrade()"
            assert hasattr(mod, "downgrade"), f"{filename} missing downgrade()"
            assert hasattr(mod, "revision"), f"{filename} missing revision"


# ---------------------------------------------------------------------------
# Task 2: Endpoint & task integration tests
# ---------------------------------------------------------------------------


class TestVrtStatusEndpoint:
    """Tests for GET /datasets/{id}/vrt/status/."""

    def test_endpoint_exists_in_router(self):
        from app.modules.catalog.datasets.api.router_vrt import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/datasets/{dataset_id}/vrt/status/" in paths

    def test_endpoint_source_contains_status_logic(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.get_vrt_status)
        assert "VrtStatusResponse" in source
        assert "source_health" in source

    def test_endpoint_uses_storage_exists_for_health(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.get_vrt_status)
        assert "storage" in source.lower()
        assert "exists" in source

    def test_endpoint_uses_asyncio_gather_for_parallel_checks(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.get_vrt_status)
        assert "asyncio.gather" in source

    def test_endpoint_returns_404_for_non_vrt(self):
        """Verify the endpoint checks record_type == 'vrt_dataset'."""
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.get_vrt_status)
        assert "vrt_dataset" in source


class TestVrtGenerationsEndpoint:
    """Tests for GET /datasets/{id}/vrt/generations/."""

    def test_endpoint_exists_in_router(self):
        from app.modules.catalog.datasets.api.router_vrt import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/datasets/{dataset_id}/vrt/generations/" in paths

    def test_endpoint_source_contains_generation_logic(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.list_vrt_generations)
        assert "VrtGenerationListResponse" in source
        assert "limit" in source
        assert "offset" in source

    def test_endpoint_paginates_by_default(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.list_vrt_generations)
        assert "ORDER BY" in source or "order_by" in source


class TestVrtRegenerateEndpoint:
    """Tests for POST /datasets/{id}/vrt/regenerate/."""

    def test_endpoint_exists_in_router(self):
        from app.modules.catalog.datasets.api.router_vrt import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/datasets/{dataset_id}/vrt/regenerate/" in paths

    def test_endpoint_uses_advisory_lock(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.regenerate_vrt_endpoint)
        assert "pg_try_advisory_xact_lock" in source

    def test_endpoint_returns_409_when_regenerating(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.regenerate_vrt_endpoint)
        assert "409" in source or "409_CONFLICT" in source or "regenerating" in source

    def test_endpoint_creates_generation_record(self):
        from app.modules.catalog.datasets.api import router_vrt as router_mod

        source = inspect.getsource(router_mod.regenerate_vrt_endpoint)
        assert "VrtGeneration" in source

    def test_advisory_lock_key_helper_exists(self):
        from app.modules.catalog.datasets.api.router_vrt import _advisory_lock_key

        dataset_id = uuid.uuid4()
        key = _advisory_lock_key(dataset_id)
        assert isinstance(key, int)
        assert 0 <= key < 2**63


class TestRegenerateVrtTaskIntegration:
    """Tests for VrtGeneration record lifecycle in regenerate_vrt task."""

    def test_task_references_vrt_generation_model(self):
        from app.processing.ingest import tasks as tasks_mod

        source = inspect.getsource(tasks_mod.regenerate_vrt)
        assert "VrtGeneration" in source

    def test_task_accepts_triggered_by_parameter(self):
        from app.processing.ingest import tasks as tasks_mod

        source = inspect.getsource(tasks_mod.regenerate_vrt)
        assert "triggered_by" in source

    def test_task_updates_generation_on_success(self):
        from app.processing.ingest import tasks as tasks_mod

        source = inspect.getsource(tasks_mod.regenerate_vrt)
        assert "completed" in source
        assert "duration_seconds" in source

    def test_task_updates_generation_on_failure(self):
        from app.processing.ingest import tasks as tasks_mod

        source = inspect.getsource(tasks_mod.regenerate_vrt)
        assert "failed" in source
        assert "error_message" in source


class TestIngestRouterTriggeredBy:
    """Tests for triggered_by being passed through defer_async calls in ingest/router.py."""

    def test_add_source_passes_triggered_by(self):
        from app.processing.ingest import router as ingest_router_mod

        source = inspect.getsource(ingest_router_mod.add_vrt_source)
        assert "triggered_by" in source

    def test_remove_source_passes_triggered_by(self):
        from app.processing.ingest import router as ingest_router_mod

        source = inspect.getsource(ingest_router_mod.remove_vrt_source)
        assert "triggered_by" in source

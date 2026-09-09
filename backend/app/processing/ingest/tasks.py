"""Procrastinate task definitions for async file ingestion.

This module re-exports all task functions and shared helpers from the
workflow-specific sub-modules so that existing imports continue to work:

    from app.processing.ingest.tasks import ingest_file, task_app
"""

from app.processing.ingest.tasks_common import (  # noqa: F401
    IngestContext,
    StagingResult,
    _append_job_warning,
    _apply_reupload_swap,
    _arcgis_type_to_column_type,
    _archive_original_file,
    _bind_task_log_context,
    _detect_and_override_geometry,
    _finalize_ingest,
    _ingest_vector_into_staging,
    _parse_temporal_fields,
    _resolve_effective_srid,
    _run_service_import_with_wfs_fallback,
    resolve_service_type,
    task_app,
)

# fix(#909): async_session is deliberately NOT re-exported here. A module-scope
# `from app.core.db import async_session` snapshots the dev-DB factory past the
# test fixture's rebinding of app.core.db; late-bind at call scope instead
# (test_layering.py enforces this).
from app.platform.cache.tiles import invalidate_catalog_cache  # noqa: F401
from app.platform.storage import get_storage  # noqa: F401
from app.processing.embeddings.helpers import defer_embedding  # noqa: F401
from app.processing.ingest.tasks_vector import (  # noqa: F401
    ingest_file,
    ingest_service,
)
from app.processing.ingest.tasks_raster import (  # noqa: F401
    create_raster_dataset,
    ingest_raster,
)
from app.processing.ingest.tasks_vrt import (  # noqa: F401
    create_vrt_dataset,
    ingest_vrt,
    regenerate_vrt,
    regenerate_vrt_staged,
)
from app.processing.ingest.tasks_reupload import (  # noqa: F401
    reupload_file,
    reupload_service,
)
from app.processing.ingest.tasks_url_fetch import (  # noqa: F401
    fetch_url,
)
from app.processing.ingest.tasks_raster_replace import (  # noqa: F401
    reupload_raster,
)
from app.processing.ingest.tasks_postgis_refresh import (  # noqa: F401
    refresh_postgis,
)
from app.processing.ingest.tasks_stac_refresh import (  # noqa: F401
    refresh_stac,
)

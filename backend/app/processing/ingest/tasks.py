"""Procrastinate task definitions for async file ingestion.

Re-exports the task functions and shared helpers from the workflow
sub-modules:

    from app.processing.ingest.tasks import ingest_file, task_app
"""

from app.processing.ingest.tasks_common import (  # noqa: F401
    IngestContext,
    _append_job_warning,
    _bind_task_log_context,
    _detect_and_override_geometry,
    _finalize_ingest,
    _parse_temporal_fields,
    _resolve_effective_srid,
    _run_service_import_with_wfs_fallback,
    resolve_service_type,
    task_app,
)
from app.processing.ingest.tasks_staging import (  # noqa: F401
    StagingResult,
    _archive_original_file,
    _ingest_vector_into_staging,
)

# async_session is not re-exported: a module-scope import snapshots the dev-DB
# factory past the test fixture's rebinding of app.core.db (test_layering.py
# enforces call-scope binding).
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
from app.processing.ingest.tasks_tileset import (  # noqa: F401
    ingest_tileset,
)
from app.processing.ingest.tasks_pointcloud import (  # noqa: F401
    ingest_pointcloud,
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
    reupload_verified_file,
    reupload_verified_refresh,
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
from app.processing.ingest.tasks_restore import (  # noqa: F401
    restore_previous_version,
)
from app.processing.ingest.tasks_stac_refresh import (  # noqa: F401
    refresh_stac,
)

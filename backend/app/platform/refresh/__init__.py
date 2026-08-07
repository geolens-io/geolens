"""Dataset refresh runs: the durable history of every replacement attempt.

feat(#1219) / ADR-002 Decision 4. Lives under ``platform/`` for the same
reason ``platform/dataset_origin.py`` does: both the catalog API (which
creates a run at dispatch and lists history) and the ingest worker (which
writes the terminal transition) need the same table and the same lifecycle
rules, and ``processing/`` may not import ``modules.catalog`` — see
``test_no_processing_imports_catalog`` in ``tests/test_layering.py``.
``platform/jobs/models.py`` already homes ``IngestJob``, a ``catalog``-schema
table, on exactly this argument.
"""

from app.platform.refresh.models import DatasetRefreshRun

__all__ = ["DatasetRefreshRun"]

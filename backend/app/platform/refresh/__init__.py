"""Dataset refresh runs: durable history of every replacement attempt.

Lives under ``platform/`` because both the catalog API and the ingest
worker need this table, and ``processing/`` may not import
``modules.catalog`` (``test_no_processing_imports_catalog``).
"""

from app.platform.refresh.models import DatasetRefreshRun

__all__ = ["DatasetRefreshRun"]

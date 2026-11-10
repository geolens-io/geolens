"""Static-analysis tests for postgresql.conf and the Map index-deferral decision."""

import re

from app.modules.catalog.maps.models import Map
from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_POSTGRESQL_CONF = _REPO_ROOT / "db" / "postgresql.conf"


def test_postgresql_conf_sets_hnsw_ef_search_default():
    """hnsw.ef_search = 100 must be a session default in postgresql.conf."""
    text = _POSTGRESQL_CONF.read_text()
    # Allow flexible whitespace around the assignment.
    assert re.search(
        r"^\s*hnsw\.ef_search\s*=\s*100",
        text,
        re.MULTILINE,
    ), "Expected `hnsw.ef_search = 100` line in db/postgresql.conf"


def test_postgresql_conf_documents_hnsw_override_rationale():
    """The new line must be accompanied by a comment explaining why."""
    text = _POSTGRESQL_CONF.read_text()
    # Comment should reference set_hnsw_recall or "per-query" so future readers
    # understand why a session default exists alongside per-transaction tuning.
    assert "set_hnsw_recall" in text or "per-query" in text or "per query" in text, (
        "Expected the hnsw.ef_search line to be accompanied by a comment "
        "referencing set_hnsw_recall (the per-query helper) for context."
    )


def test_postgresql_conf_enables_lock_wait_and_io_observability():
    """Lock waits and I/O time must be visible without an ALTER SYSTEM first."""
    text = _POSTGRESQL_CONF.read_text()
    for setting in ("log_lock_waits", "track_io_timing"):
        assert re.search(rf"^\s*{setting}\s*=\s*on\b", text, re.MULTILINE), (
            f"Expected `{setting} = on` in db/postgresql.conf"
        )


def test_maps_table_has_no_index_on_visibility():
    """The deferred visibility index is a decision; adding one needs a fresh EXPLAIN."""
    indexed = {
        column.name for index in Map.__table__.indexes for column in index.columns
    }
    assert "visibility" not in indexed

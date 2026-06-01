"""Static-analysis tests for Phase 271 / DBM-01 + DBM-06 config + doc deliverables."""

import re

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_POSTGRESQL_CONF = _REPO_ROOT / "db" / "postgresql.conf"
_MAP_MODEL = (
    _REPO_ROOT / "backend" / "app" / "modules" / "catalog" / "maps" / "models.py"
)


def test_postgresql_conf_sets_hnsw_ef_search_default():
    """DBM-01: hnsw.ef_search = 100 must be a session default in postgresql.conf."""
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


def test_map_model_documents_dbm_06_deferral():
    """DBM-06: Map.__table_args__ must have a documented deferral with a revisit trigger."""
    text = _MAP_MODEL.read_text()
    assert "DBM-06" in text, "Map model must reference DBM-06 in a deferral comment."
    # Trigger condition should mention seq-scan / EXPLAIN / metric — give some
    # flexibility on phrasing.
    triggers = ["seq scan", "seq-scan", "EXPLAIN", "metric"]
    assert any(t in text for t in triggers), (
        "DBM-06 deferral must name a clear revisit trigger (e.g., 'EXPLAIN shows seq scan')."
    )


def test_db_index_deferrals_doc_exists_with_dbm_06():
    """DBM-06 deferral rationale stays inline with the model for public release."""
    text = _MAP_MODEL.read_text()
    assert "DBM-06" in text
    assert "Map.visibility" in text or "Map visibility" in text

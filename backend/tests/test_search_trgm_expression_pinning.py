"""T-1 regression: catalog-search text filter must emit the indexed
``lower(catalog.immutable_unaccent(...))`` expression.

The trigram GIN indexes from migration 0010 (``ix_records_title_trgm``,
``ix_records_summary_trgm``, ``ix_record_keywords_keyword_trgm``) are built on
``lower(catalog.immutable_unaccent(<col>))`` (an IMMUTABLE function). The query
MUST use that exact schema-qualified function. A bare ``func.unaccent()`` renders
unqualified and resolves via search_path to ``public.unaccent`` (STABLE), which
the planner cannot match to the indexed expression -> silent seq scan on the
high-traffic ``/search`` path.

This pins the ``service_filters`` query the same way
``test_phase_279_admin_polish`` pins the admin audit-search query, so a future
"simplify the search filter" refactor that reverts to ``unaccent``/ILIKE is
caught at test time rather than as a silent latency regression.
"""

from sqlalchemy.dialects import postgresql

from app.modules.catalog.search.service_filters import _build_text_filter


def _part_sql(part_key: str) -> str:
    # _build_text_filter returns (clause, parts_dict); the parts are the
    # individual trigram LIKE expressions (and exists() subqueries) that the
    # combined clause is built from. We compile each part to inspect its SQL.
    _clause, parts = _build_text_filter("park")
    return str(parts[part_key].compile(dialect=postgresql.dialect())).lower()


def test_title_and_summary_use_immutable_unaccent_not_bare_unaccent():
    for key in ("title_match", "summary_match"):
        sql = _part_sql(key)
        # Index-matching, schema-qualified IMMUTABLE form must be present...
        assert "lower(catalog.immutable_unaccent(" in sql, (key, sql)
        # ...and the unqualified STABLE form (which seq-scans) must NOT appear.
        assert "lower(unaccent(" not in sql, (key, sql)


def test_keyword_like_subquery_uses_immutable_unaccent():
    sql = _part_sql("keyword_partial_exists")
    assert "lower(catalog.immutable_unaccent(" in sql, sql
    assert "record_keywords.keyword" in sql, sql
    assert "lower(unaccent(" not in sql, sql


def test_title_summary_target_the_right_columns():
    assert "records.title" in _part_sql("title_match")
    assert "records.summary" in _part_sql("summary_match")

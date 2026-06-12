"""BUG-027: catalog search _build_text_filter must escape %, _, and \\.

service_filters._build_text_filter() composed its ILIKE pattern as
``func.concat("%", immutable_unaccent(query_text.lower()), "%")`` and called
``.like(unaccented_like)`` on title/summary/keyword/contact WITHOUT escaping the
user-supplied string and WITHOUT an explicit ``escape=`` kwarg. A search of "%"
matched every record (pattern "%%"), "_" matched any single character, and the
repo's own escape_ilike() helper (used at every other search surface — maps,
admin, audit, embed-token) was not applied here.

Fix: escape_ilike() wraps query_text before composing the pattern, and every
.like() call passes escape="\\" so the emitted SQL carries ESCAPE '\\'.

These are SQL-compilation unit tests (no DB required). The catalog text filter
embeds REGCONFIG literals (websearch_to_tsquery) that the dialect cannot render
under literal_binds, so we compile with bound parameters and inspect (a) the
ESCAPE clauses in the SQL string and (b) the escaped pattern in the bound params.
"""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.search.service_filters import _build_text_filter


def _compile_filter(query_text: str):
    """Compile the text-filter clause for ``query_text``.

    Returns ``(sql_string, param_values)`` where ``sql_string`` has placeholders
    (not literal_binds — REGCONFIG literals are unrenderable) and ``param_values``
    is the list of bound-parameter values.

    ``_build_text_filter`` returns ``(clause, parts)``; only the clause is needed.
    """
    clause, _parts = _build_text_filter(query_text)
    compiled = select(Record.id).where(clause).compile(dialect=postgresql.dialect())
    return str(compiled), list(compiled.params.values())


class TestCatalogSearchEscapeIlikeSql:
    """SQL-compilation unit tests for BUG-027."""

    def test_percent_literal_escaped(self):
        """q='100%' must bind the ILIKE pattern fragment as '100\\%' (escaped).

        (The raw '100%' is also bound separately for websearch_to_tsquery — that
        is correct; only the ILIKE/.like() pattern fragment must be escaped.)
        """
        _sql, params = _compile_filter("100%")
        assert r"100\%" in params, (
            f"Expected escaped percent fragment '100\\%' in bound params, got:\n{params}"
        )

    def test_underscore_literal_escaped(self):
        """q='a_b' must bind the pattern fragment as 'a\\_b' (escaped)."""
        _sql, params = _compile_filter("a_b")
        assert r"a\_b" in params, (
            f"Expected escaped underscore fragment 'a\\_b' in bound params, got:\n{params}"
        )

    def test_backslash_literal_doubled(self):
        """q='a\\b' (literal backslash) must be doubled in the bound pattern."""
        _sql, params = _compile_filter("a\\b")
        assert "a\\\\b" in params, (
            f"Expected doubled backslash 'a\\\\b' in bound params, got:\n{params}"
        )

    def test_escape_clause_present_on_every_like(self):
        """Every .like() branch must emit ESCAPE so the escape char is explicit.

        title/summary/keyword/contact each contribute one ILIKE ... ESCAPE.
        """
        sql, _params = _compile_filter("anything")
        assert sql.upper().count("ESCAPE") >= 4, (
            f"Expected >=4 ESCAPE clauses (title/summary/keyword/contact), got:\n{sql}"
        )

    def test_plain_text_search_unaffected(self):
        """Normal text without special chars passes through unmodified."""
        _sql, params = _compile_filter("parcels")
        assert "parcels" in params, (
            f"Expected 'parcels' in bound params, got:\n{params}"
        )

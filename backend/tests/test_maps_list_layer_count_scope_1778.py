"""fix(#1778): the maps gallery listing must not aggregate the whole layer table.

Codebase audit 2026-08-30 (8dc529f17): ``list_maps`` read its per-map layer
count from an uncorrelated ``GROUP BY map_id`` subquery LEFT JOINed onto the
page. PostgreSQL cannot push a LIMIT through a left join, so every page of the
gallery aggregated every row of ``catalog.map_layers`` regardless of page size,
search term or visibility filter.

The counts now come from a second statement keyed on the ids the page actually
returned, so the aggregate is bounded by the page at every offset. These tests
pin both halves of that: the page statement no longer mentions ``map_layers``,
and the statement that does is restricted to the page's ids.

No database: a recording session double captures the emitted statements and
compiles them, the way ``test_search_trgm_expression_pinning`` pins the search
filter's SQL.
"""

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service_crud import list_maps


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalar_one(self):
        return self._rows[0][0]


class _RecordingSession:
    """Captures every statement ``list_maps`` emits and answers each in turn."""

    def __init__(self, page_rows: list, layer_count_rows: list, total: int) -> None:
        self.sql: list[str] = []
        self._replies = [
            _Result([(total,)]),
            _Result(page_rows),
            _Result(layer_count_rows),
        ]

    async def execute(self, statement):
        self.sql.append(str(statement.compile(dialect=postgresql.dialect())).lower())
        return self._replies[len(self.sql) - 1]


def _map(map_id: uuid.UUID) -> Map:
    return Map(id=map_id, name="Transit", description=None, visibility="public")


@pytest.mark.anyio
async def test_page_statement_does_not_touch_the_layer_table_1778():
    """An empty page so the assertion, not the row shape, is what reports."""
    session = _RecordingSession([], [], 0)

    await list_maps(session, skip=0, limit=50)

    page_sql = session.sql[1]
    assert "map_layers" not in page_sql, page_sql
    assert "group by" not in page_sql, page_sql


@pytest.mark.anyio
async def test_layer_counts_are_restricted_to_the_page_ids_1778():
    map_id = uuid.uuid4()
    session = _RecordingSession([(_map(map_id), "ada")], [(map_id, 7)], 1)

    maps, total = await list_maps(session, skip=0, limit=50)

    counts_sql = session.sql[2]
    assert "catalog.map_layers" in counts_sql, counts_sql
    assert "map_layers.map_id in" in counts_sql, counts_sql
    assert maps[0]["layer_count"] == 7
    assert total == 1


@pytest.mark.anyio
async def test_a_map_with_no_layers_still_reports_zero_1778():
    """The removed LEFT JOIN carried a ``coalesce(..., 0)``; keep its result."""
    map_id = uuid.uuid4()
    session = _RecordingSession([(_map(map_id), "ada")], [], 1)

    maps, _total = await list_maps(session, skip=0, limit=50)

    assert maps[0]["layer_count"] == 0


@pytest.mark.anyio
async def test_an_empty_page_skips_the_layer_count_query_1778():
    session = _RecordingSession([], [], 0)

    maps, total = await list_maps(session, skip=0, limit=50)

    assert (maps, total) == ([], 0)
    assert len(session.sql) == 2

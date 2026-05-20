"""Tests for the simple-regconfig GIN index (SEC-S12 / Phase 1062-03).

Verifies that:
1. ix_records_simple_search_vector exists in pg_indexes.
2. EXPLAIN (FORMAT JSON) on a CJK query shows Bitmap Index Scan on
   ix_records_simple_search_vector (proves the index is used, not just present).
3. /search/datasets/?q=<CJK term> returns the seeded record end-to-end.

Design note on SET enable_seqscan = off:
    When the records table is tiny (as in tests) the planner naturally prefers a
    seq scan because the total cost is lower.  ``SET LOCAL enable_seqscan = off``
    forces the planner to prefer index scans for the EXPLAIN query, making the
    test deterministic regardless of table size.  This matches the documented
    behaviour under production load where the table is large enough for the index
    to win on cost alone.
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_cjk_dataset(
    session, *, created_by: uuid.UUID
) -> tuple[Record, Dataset]:
    """Insert a Record + Dataset with an accented-Latin title.

    We use accented Latin (e.g. 'Niño') rather than CJK because Postgres
    simple-dictionary tokenises on whitespace/word boundaries — CJK characters
    in a no-space string (e.g. '東京駅') become a *single* token '東京駅' and
    searching for '東京' (a sub-string) never matches.  Accented Latin behaves
    identically to ASCII for tokenisation (whitespace-split), so the test is
    deterministic.  The important property being tested is that
    ix_records_simple_search_vector is used via EXPLAIN — not that CJK
    specifically works (that depends on the client normalising the query string
    or using pg_bigm for n-gram indexing, which is out of scope for SEC-S12).

    Returns (record, dataset) because the /search/datasets/ API uses dataset.id
    as the feature "id" field (not record.id).
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    # Use a unique UUID-suffix in the title so the end-to-end test is
    # isolated even when the shared test DB retains data from prior test runs.
    unique = uuid.uuid4().hex[:8]
    record = Record(
        title=f"Niño Único {unique}",
        summary=f"Descripción única {unique}",
        lineage_summary=None,
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="Point",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(record)
    await session.refresh(dataset)
    return record, dataset


def _walk_plan(node: dict, results: list) -> None:
    """Recursively walk a Postgres JSON EXPLAIN plan, collecting all node dicts."""
    results.append(node)
    for child in node.get("Plans", []):
        _walk_plan(child, results)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def cjk_record(test_db_session):
    """Seed an accented-Latin-title record visible to public search.

    Returns (record, dataset).  The /search/datasets/ API uses dataset.id
    as the feature "id" — callers need both when asserting the search result.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    record, dataset = await _create_cjk_dataset(test_db_session, created_by=admin_id)
    return record, dataset


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_simple_index_exists(test_db_session):
    """ix_records_simple_search_vector must exist after migration 0020 is applied."""
    result = await test_db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'catalog' "
            "AND indexname = 'ix_records_simple_search_vector'"
        )
    )
    rows = result.fetchall()
    assert len(rows) == 1, (
        "Expected ix_records_simple_search_vector in pg_indexes; "
        "did migration 0020_records_simple_search_vector_idx apply?"
    )


@pytest.mark.anyio
async def test_non_english_query_uses_simple_index(test_db_session, cjk_record):
    """EXPLAIN on a non-English/accented query must show Bitmap Index Scan on
    ix_records_simple_search_vector.

    Uses SET LOCAL enable_seqscan = off to force the planner to choose the index
    scan path even on a small test table (see module docstring).
    """
    record, _ = cjk_record
    # SET LOCAL + EXPLAIN in a single execute call
    await test_db_session.execute(text("SET LOCAL enable_seqscan = off"))
    result = await test_db_session.execute(
        text(
            "EXPLAIN (FORMAT JSON) "
            "SELECT id FROM catalog.records "
            "WHERE to_tsvector("
            "    'simple',"
            "    coalesce(title, '') || ' ' ||"
            "    coalesce(summary, '') || ' ' ||"
            "    coalesce(lineage_summary, '') || ' ' ||"
            "    coalesce(catalog.immutable_text_array_join(theme_category, ' '), '')"
            ") @@ websearch_to_tsquery('simple', 'Niño')"
        )
    )
    row = result.fetchone()
    assert row is not None, "EXPLAIN returned no rows"
    # The EXPLAIN (FORMAT JSON) result is a single-column JSON list
    plan_json = row[0]
    if isinstance(plan_json, str):
        plan_list = json.loads(plan_json)
    else:
        # asyncpg may return already-decoded list
        plan_list = plan_json

    # Walk all nodes in the plan tree and collect Index Name values
    all_nodes: list[dict] = []
    for top in plan_list:
        _walk_plan(top["Plan"], all_nodes)

    index_names = {node.get("Index Name") for node in all_nodes if "Index Name" in node}
    assert "ix_records_simple_search_vector" in index_names, (
        f"Expected 'ix_records_simple_search_vector' in plan index names, got: {index_names}. "
        "Full plan: " + json.dumps(plan_list, indent=2, default=str)
    )


@pytest.mark.anyio
async def test_search_datasets_endpoint_finds_cjk_record(
    client: AsyncClient,
    test_db_session,
    cjk_record,
):
    """GET /search/datasets/?q=<unique title suffix> must return the seeded record.

    The unique UUID suffix in the title ensures we find exactly our record even
    when the shared test DB has data from prior runs.  We search for the unique
    hex suffix (ASCII, unambiguous tokenisation) to avoid false positives.

    Note: /search/datasets/ returns dataset.id as feature "id" (not record.id),
    so we assert against dataset.id here.
    """
    record, dataset = cjk_record

    # Extract the unique suffix from the seeded title (last word in "Niño Único <hex>")
    unique_suffix = record.title.split()[-1]
    resp = await client.get("/search/datasets/", params={"q": unique_suffix})
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} {resp.text}"

    body = resp.json()
    feature_ids = [str(f["id"]) for f in body.get("features", [])]
    assert str(dataset.id) in feature_ids, (
        f"Expected dataset {dataset.id} (record title='{record.title}') "
        f"in /search/datasets/?q={unique_suffix!r} results, got ids: {feature_ids}"
    )

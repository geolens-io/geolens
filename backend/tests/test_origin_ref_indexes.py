"""EXPLAIN verification for the origin_ref duplicate-source guard indexes.

perf(#1324). Follow-up to #1286 / PR #1320, which re-keyed the
service-preview guard (``catalog/sources/router.py``) and the STAC-import
guard (``catalog/sources/stac_router.py``) from ``origin_uri`` onto the
structured ``origin_ref`` identity. Migration 0040_dataset_origin_ref_indexes
adds the two partial expression indexes the issue named, plus a third on
plain ``source_url`` (see that migration's docstring, and the codex review on
PR #1365, for why the third one is required for the first two to matter).
This file proves the FULL guard queries -- exactly as written in production,
including their legacy source_url fallback branch -- actually hit the new
indexes via a ``BitmapOr``, not just that the indexes exist (that narrower
check lives in ``TestOrmAndMigrationShape`` in ``test_dataset_source_state.py``
for the sibling ``ix_datasets_origin_uri`` index) and not just that the
origin_ref branch is indexable in isolation.

``SET LOCAL enable_seqscan = off`` forces the planner to prefer an index scan
even though the test table is far too small for the index to win on cost
alone -- see ``test_search_simple_regconfig.py`` for the same technique and
its rationale.

History, for anyone re-deriving why there are three indexes here: both guard
queries are shaped ``WHERE (origin_ref match) OR (legacy source_url
fallback) AND source_format = ... AND created_by = ...``. Postgres only
folds a top-level OR into a bitmap index scan when EVERY disjunct has an
index path of its own. An earlier version of this migration indexed only
the origin_ref keys #1324 named, leaving the source_url fallback disjunct
unindexed -- codex's round-1 review on PR #1365 caught that this made both
new indexes dead weight against the real queries (confirmed by EXPLAIN: the
full guard predicate still resolved to a sequential scan). Adding
``ix_datasets_source_url`` gives the fallback disjunct an index path too, so
postgres builds a BitmapOr combining it with the matching origin_ref index --
which is what the tests below assert.

Round 2 then caught that a PLAIN (btree) `source_url` index carries its own
risk -- see the test class below -- resolved by making it `USING hash`.
Round 4 caught the same class on the two `origin_ref` indexes: WFS/OGC API
`layer_name` allows up to 500 multibyte characters and flows into
`origin_ref->>'layer_id'`, so a long multibyte `url` combined with a long
multibyte `layer_id` can exceed the btree ceiling in the COMPOSITE key even
when a single-column index would not have. All three are now `USING hash`,
which closes the class rather than patching it per column -- postgres hash
indexes store only a fixed-size hash, never the value, so none of them has
a size ceiling at all. The tradeoff: hash indexes are single-column, so
`layer_id` is no longer part of any index -- the service-preview guard's
`layer_id` check becomes a residual Filter, confirmed acceptable by EXPLAIN
(url alone remains the selective key).
"""

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import and_, or_, text
from sqlalchemy.dialects import postgresql

from app.modules.catalog.datasets.domain.models import Dataset, Record
from tests.factories import get_user_id

_ORIGIN_REF_INDEX_NAMES = (
    "ix_datasets_origin_ref_url",
    "ix_datasets_origin_ref_asset_href",
    "ix_datasets_source_url",
)


def _walk_plan(node: dict, results: list) -> None:
    """Recursively walk a Postgres JSON EXPLAIN plan, collecting all node dicts."""
    results.append(node)
    for child in node.get("Plans", []):
        _walk_plan(child, results)


async def _explain_index_names(session, stmt) -> set[str]:
    """Run EXPLAIN (FORMAT JSON) on ``stmt`` and collect every Index Name used."""
    compiled = stmt.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    result = await session.execute(text(f"EXPLAIN (FORMAT JSON) {compiled}"))
    row = result.fetchone()
    assert row is not None, "EXPLAIN returned no rows"
    plan_json = row[0]
    plan_list = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
    all_nodes: list[dict] = []
    for top in plan_list:
        _walk_plan(top["Plan"], all_nodes)
    return {node.get("Index Name") for node in all_nodes if "Index Name" in node}


class _SeededRow:
    """A Record + Dataset pair this module owns, deleted by id in teardown.

    Not the shared ``clean_tables`` fixture: that TRUNCATEs the whole
    catalog.datasets/catalog.records tables, which is safe against CI's
    per-worker database but not against a developer's shared host-side test
    database (this suite is regularly run that way -- see AGENTS.md). A
    delete scoped to exactly the ids this fixture created is safe either way.
    """

    def __init__(self, record: Record, dataset: Dataset) -> None:
        self.record = record
        self.dataset = dataset


@pytest.fixture
async def seeded_rows(test_db_session):
    created: list[_SeededRow] = []

    async def _seed(*, created_by, source_format, origin_ref, source_url=None):
        tag = uuid.uuid4().hex[:12]
        record = Record(
            title=f"origin-ref-index test {tag}",
            visibility="public",
            record_status="published",
            record_type="vector_dataset",
            created_by=created_by,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=f"ds_{tag}",
            source_format=source_format,
            origin_ref=origin_ref,
            source_url=source_url,
        )
        test_db_session.add(dataset)
        await test_db_session.flush()
        row = _SeededRow(record, dataset)
        created.append(row)
        return row

    await test_db_session.commit()
    yield _seed

    for row in created:
        await test_db_session.execute(
            sa.delete(Dataset).where(Dataset.id == row.dataset.id)
        )
        await test_db_session.execute(
            sa.delete(Record).where(Record.id == row.record.id)
        )
    await test_db_session.commit()


@pytest.mark.anyio
async def test_origin_ref_indexes_exist(test_db_session):
    """All three indexes from migration 0040 must be present."""
    result = await test_db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'catalog' AND tablename = 'datasets' "
            "AND indexname = ANY(:names)"
        ),
        {"names": list(_ORIGIN_REF_INDEX_NAMES)},
    )
    names = {row[0] for row in result.fetchall()}
    assert names == set(_ORIGIN_REF_INDEX_NAMES), (
        "Expected all three origin_ref/source_url indexes in pg_indexes; did "
        "migration 0040_dataset_origin_ref_indexes apply?"
    )


@pytest.mark.anyio
async def test_service_guard_full_query_uses_bitmap_or(test_db_session, seeded_rows):
    """The service-preview guard's FULL WHERE clause -- the real OR of the
    origin_ref match and the legacy source_url fallback, exactly as built in
    sources/router.py's preview_service_layer -- must resolve through a
    BitmapOr of ix_datasets_origin_ref_url and ix_datasets_source_url, not a
    table-wide scan.

    Deliberately a datasets-only probe, dropping the guard's Record join and
    created_by filter (CI finding, batch run 31417356444): a joined query's
    plan can depend on relative table statistics, which pytest-xdist worker
    databases don't control -- other tests running in the same worker leave
    an arbitrary number of records/datasets rows behind, and at some ratio
    the planner can prefer driving from records_pkey over the origin_ref/
    source_url predicate this test exists to check. The Dataset-only WHERE
    clause below is the part these indexes actually serve; created_by
    filtering rides on ix_records_created_by regardless and isn't what this
    file verifies.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    target_url = f"https://gis.example.test/wfs/{uuid.uuid4().hex[:8]}"
    target_layer = f"topp:{uuid.uuid4().hex[:8]}"

    await seeded_rows(
        created_by=admin_id,
        source_format="wfs",
        origin_ref={
            "kind": "service",
            "service_type": "wfs",
            "url": target_url,
            "layer_id": target_layer,
        },
    )

    # Mirrors the full WHERE clause built in sources/router.py's
    # preview_service_layer (the ``canonical_layer_id is not None`` arm),
    # including the legacy source_url fallback disjunct -- minus the join,
    # see the docstring above.
    origin_ref_url = Dataset.origin_ref["url"].astext
    origin_ref_layer_id = Dataset.origin_ref["layer_id"].astext
    stmt = sa.select(Dataset.id).where(
        or_(
            and_(
                Dataset.origin_ref["service_type"].astext == "wfs",
                origin_ref_url == target_url,
                origin_ref_layer_id == target_layer,
            ),
            and_(
                or_(origin_ref_url.is_(None), origin_ref_layer_id.is_(None)),
                Dataset.source_url == target_url,
            ),
        ),
        Dataset.source_format == "wfs",
    )

    index_names = await _explain_index_names(test_db_session, stmt)
    assert {"ix_datasets_origin_ref_url", "ix_datasets_source_url"} <= index_names, (
        f"Expected both ix_datasets_origin_ref_url and ix_datasets_source_url "
        f"in the plan (as a BitmapOr), got: {index_names}"
    )


@pytest.mark.anyio
async def test_stac_guard_full_query_uses_bitmap_or(test_db_session, seeded_rows):
    """The STAC-import guard's FULL WHERE clause -- the real OR of the
    origin_ref->>'asset_href' match and the legacy source_url fallback,
    exactly as built in stac_router.py's batch duplicate check -- must
    resolve through a BitmapOr of ix_datasets_origin_ref_asset_href and
    ix_datasets_source_url, not a table-wide scan.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    target_href = f"https://stac.example.test/assets/{uuid.uuid4().hex[:8]}.tif"

    await seeded_rows(
        created_by=admin_id,
        source_format="stac",
        origin_ref={"kind": "stac", "asset_href": target_href},
    )

    # Mirrors the batch duplicate-check in stac_router.py's import handler:
    # origin_ref->>'asset_href' IN (hrefs) OR (origin_uri IS NULL AND
    # source_url IN (hrefs)), scoped to source_format = 'stac'.
    stmt = sa.select(
        Dataset.origin_ref["asset_href"].astext.label("asset_href"),
        Dataset.source_url,
    ).where(
        or_(
            Dataset.origin_ref["asset_href"].astext.in_([target_href]),
            and_(
                Dataset.origin_uri.is_(None),
                Dataset.source_url.in_([target_href]),
            ),
        ),
        Dataset.source_format == "stac",
    )

    index_names = await _explain_index_names(test_db_session, stmt)
    assert {
        "ix_datasets_origin_ref_asset_href",
        "ix_datasets_source_url",
    } <= index_names, (
        f"Expected both ix_datasets_origin_ref_asset_href and "
        f"ix_datasets_source_url in the plan (as a BitmapOr), got: {index_names}"
    )


# ---------------------------------------------------------------------------
# All three indexes are USING hash, not btree (codex review rounds 2 and 4).
# A btree index stores the value itself and has a ~2704-byte tuple limit on
# standard 8kB pages; VARCHAR(2000) caps source_url's CHARACTER count, not
# bytes, and WFS/OGC API layer_name (up to 500 multibyte characters) flows
# into origin_ref->>'layer_id', so a multibyte-heavy value can pass every
# length check that exists and still break a btree index (reproduced during
# development: 2000 random astral-plane characters is 8000 UTF-8 bytes, and
# a scratch btree index on such a row fails with "index row size exceeds
# btree ... maximum"). A hash index stores only a fixed-size hash of the
# value, so it has no such ceiling regardless of source string length --
# these three tests prove that holds for each of the real indexes, not just
# a scratch table.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_source_url_hash_index_tolerates_byte_oversize_value(
    test_db_session, seeded_rows
):
    """A source_url whose UTF-8 encoding would break a btree index (see the
    module docstring above) must insert and index cleanly under
    ix_datasets_source_url's hash access method, and still be found by an
    equality lookup mirroring the guards' own predicate.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    # 722 characters total -- comfortably inside the column's VARCHAR(2000)
    # CHARACTER cap -- but 2822 UTF-8 bytes, over the btree ceiling. This is
    # exactly the shape the round-2 finding described: a value the column
    # (and any character-length validation) accepts without complaint.
    oversize_url = "https://example.test/" + ("\U0001f000" * 700)
    assert len(oversize_url) <= 2000, "fixture must satisfy VARCHAR(2000)"
    assert len(oversize_url.encode("utf-8")) > 2704, (
        "fixture must exceed the btree ceiling to be a meaningful regression check"
    )

    await seeded_rows(
        created_by=admin_id,
        source_format="wfs",
        origin_ref=None,
        source_url=oversize_url,
    )

    stmt = sa.select(Dataset.id).where(Dataset.source_url == oversize_url)
    index_names = await _explain_index_names(test_db_session, stmt)
    assert "ix_datasets_source_url" in index_names, (
        f"Expected the hash index to serve an equality lookup on an "
        f"oversize source_url, got: {index_names}"
    )

    result = await test_db_session.execute(stmt)
    assert result.scalar_one_or_none() is not None, (
        "the oversize row must actually be findable via the index, not just "
        "planned through it"
    )


@pytest.mark.anyio
async def test_origin_ref_url_hash_index_tolerates_byte_oversize_value(
    test_db_session, seeded_rows
):
    """The round-4 finding's exact shape: a long multibyte
    origin_ref->>'url' combined with a multibyte layer_id (WFS/OGC API
    layer_name allows up to 500 characters, no charset restriction) --
    which would have exceeded a composite btree's tuple limit even though
    neither value alone might -- must insert and index cleanly under
    ix_datasets_origin_ref_url's hash access method.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    oversize_url = "https://example.test/" + ("\U0001f000" * 700)
    oversize_layer = "テスト" * 100  # 300 chars, well under 500
    assert len(oversize_url.encode("utf-8")) > 2704

    await seeded_rows(
        created_by=admin_id,
        source_format="wfs",
        origin_ref={
            "kind": "service",
            "service_type": "wfs",
            "url": oversize_url,
            "layer_id": oversize_layer,
        },
    )

    stmt = sa.select(Dataset.id).where(Dataset.origin_ref["url"].astext == oversize_url)
    index_names = await _explain_index_names(test_db_session, stmt)
    assert "ix_datasets_origin_ref_url" in index_names, (
        f"Expected the hash index to serve an equality lookup on an "
        f"oversize origin_ref->>'url', got: {index_names}"
    )

    result = await test_db_session.execute(stmt)
    assert result.scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_origin_ref_asset_href_hash_index_tolerates_byte_oversize_value(
    test_db_session, seeded_rows
):
    """Same shape as the two tests above, for the STAC guard's
    origin_ref->>'asset_href' hash index.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    oversize_href = "https://example.test/" + ("\U0001f000" * 700)
    assert len(oversize_href.encode("utf-8")) > 2704

    await seeded_rows(
        created_by=admin_id,
        source_format="stac",
        origin_ref={"kind": "stac", "asset_href": oversize_href},
    )

    stmt = sa.select(Dataset.id).where(
        Dataset.origin_ref["asset_href"].astext == oversize_href
    )
    index_names = await _explain_index_names(test_db_session, stmt)
    assert "ix_datasets_origin_ref_asset_href" in index_names, (
        f"Expected the hash index to serve an equality lookup on an "
        f"oversize origin_ref->>'asset_href', got: {index_names}"
    )

    result = await test_db_session.execute(stmt)
    assert result.scalar_one_or_none() is not None

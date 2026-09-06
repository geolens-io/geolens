"""Foreign-stamped rows must not starve the HNSW candidate window (#1546 r2).

The configuration predicate is applied AFTER the approximate index scan has
chosen its candidates. With a fixed `hnsw.ef_search` and no iterative scan, the
index hands back at most that many rows and the filter runs on them, so a
catalog whose nearest neighbours are mostly rows the filter rejects can have
every candidate discarded before a usable one is visited. Semantic search then
returns nothing and falls back to FTS while matching vectors sit in the table.

The realistic way in is a partly complete regenerate after a configuration
change: most rows carry the superseded stamp, and they are exactly as near the
query as their replacements would be.

This is not a defect #1546 introduced. A model-only filter starves the same way
on a catalog holding two models' rows in one index, which is the state #1506
was written for. #1546 made the predicate more selective, so it made the window
easier to exhaust, and the fix covers both.

WHY THIS TESTS `resolve_semantic_arm` AND NOT THE SEARCH ENDPOINT: the defect only
exists when the plan actually uses the HNSW index, and on a table this size
Postgres will not choose it unless pushed. `enable_seqscan = off` alone is not
enough and the first draft of this test was vacuous because of it: the planner
switched to the `uq_record_embedding_model` btree, sorted 155 rows by distance,
and found every live row with iterative scan on or off. `enable_sort = off`
removes that escape, because only an ordered index scan can then satisfy the
ORDER BY. Both have to be set on the session the query runs in, which an HTTP
request is not.

Measured on pgvector 0.8.5, with the plan forced:

    iterative_scan=off             Rows Removed by Filter: 100    returned 0
    iterative_scan=relaxed_order   Rows Removed by Filter: 150    returned 5

The first line is the defect: exactly `ef_search` candidates examined, every
one of them rejected, nothing returned while five usable vectors sit in the
table.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (including pgvector >= 0.8.0)
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.core.persistent_config import (
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    SEMANTIC_SEARCH_ENABLED,
)
from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.search import service_semantic
from app.modules.catalog.search.service_filters import SearchFilters
from app.processing.embeddings import helpers
from app.processing.embeddings.helpers import embedding_config_fingerprint
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import resolve_embedding_base_url

from tests.factories import create_dataset, get_user_id

_DIMS = 1536
# More foreign rows than `ef_search`, all nearer the query than any live row.
# 150 against a window of 100 is what makes the window run out.
_FOREIGN_ROWS = 150
_LIVE_ROWS = 5
_EF_SEARCH = 100
_FOREIGN_URL = "https://starved-endpoint.invalid/v1"


@pytest.fixture
async def semantic_search_on(test_db_session):
    previous = await SEMANTIC_SEARCH_ENABLED.get(test_db_session)
    await SEMANTIC_SEARCH_ENABLED.set(test_db_session, True)
    yield
    await SEMANTIC_SEARCH_ENABLED.set(test_db_session, previous)


@pytest.fixture(autouse=True)
def _fresh_has_embeddings_cache():
    helpers._has_embeddings_cache.clear()
    yield
    helpers._has_embeddings_cache.clear()


def _vector(angle: float) -> list[float]:
    """A unit vector in a band this file owns, rotated by `angle`.

    Band [800, 810) keeps these rows away from every other suite's vectors, so
    the candidate window this test fills is filled by this test.
    """
    vec = [0.0] * _DIMS
    vec[800] = 1.0
    vec[801] = angle
    magnitude = sum(v * v for v in vec) ** 0.5
    return [v / magnitude for v in vec]


async def _seed(session, name: str, *, fingerprint: str, angle: float) -> uuid.UUID:
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=user_id, name=name)
    record_id = dataset.record_id
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=_vector(angle),
            model_name=await EMBEDDING_MODEL.get(session),
            config_fingerprint=fingerprint,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await session.commit()
    return record_id


@pytest.mark.anyio
async def test_foreign_rows_nearer_than_live_ones_do_not_starve_the_scan(
    test_db_session,
    semantic_search_on,
):
    """150 rejected neighbours in front of 5 usable ones, window of 100."""
    session = test_db_session
    model_name = await EMBEDDING_MODEL.get(session)
    dimensions = await EMBEDDING_DIMS.get(session)
    base_url = await resolve_embedding_base_url(session)
    live = embedding_config_fingerprint(model_name, dimensions, base_url)
    foreign = embedding_config_fingerprint(model_name, dimensions, _FOREIGN_URL)
    assert live != foreign

    # Nearest first: the foreign rows sit almost exactly on the query, the live
    # ones sit further out but well inside the 0.7 cosine cutoff.
    for index in range(_FOREIGN_ROWS):
        await _seed(
            session,
            f"Starve Foreign {index}",
            fingerprint=foreign,
            angle=0.001 * (index + 1),
        )
    live_ids = {
        await _seed(
            session,
            f"Starve Live {index}",
            fingerprint=live,
            angle=0.40 + 0.01 * index,
        )
        for index in range(_LIVE_ROWS)
    }

    query_vector = _vector(0.0)

    # Force the ordered index path; see the module docstring for why both are
    # needed and what the first draft of this test proved without the second.
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    await session.execute(text("SET LOCAL enable_sort = off"))

    # Non-vacuity, part one: the plan really does go through the HNSW index, so
    # a post-filter window exists to be starved. Explained against the same
    # shape `resolve_semantic_arm` builds — the configuration predicate, the 0.7
    # cutoff, ordered by distance with a limit — because a simpler query can
    # take a different plan, which is exactly how the earlier draft fooled
    # itself.
    plan = "\n".join(
        row[0]
        for row in (
            await session.execute(
                text(
                    "EXPLAIN SELECT record_id FROM catalog.record_embeddings "
                    "WHERE model_name = :model "
                    "AND (config_fingerprint IS NULL OR config_fingerprint = :fp) "
                    "AND embedding <=> CAST(:q AS vector) <= 0.7 "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {
                    "model": model_name,
                    "fp": live,
                    "q": str(query_vector),
                    "k": _LIVE_ROWS,
                },
            )
        ).all()
    )
    assert "ix_record_embeddings_hnsw" in plan, plan

    with patch.object(
        service_semantic,
        "generate_embedding",
        new=AsyncMock(return_value=query_vector),
    ):
        arm = await service_semantic.resolve_semantic_arm(
            session,
            SearchFilters(q="starvation query"),
            select(Record.id),
            depth=_LIVE_ROWS,
        )

    # Non-vacuity, part two: the vector arm ran rather than bailing early.
    assert arm is not None
    assert arm.query_vector == query_vector
    ranks = arm.ranks(_LIVE_ROWS)

    returned = {uuid.UUID(record_id) for record_id in ranks}
    assert returned & live_ids, (
        "no live row survived the candidate window: "
        f"{len(ranks)} ranks returned from {_FOREIGN_ROWS} foreign rows in front "
        f"of {_LIVE_ROWS} live ones at ef_search={_EF_SEARCH}"
    )
    # And nothing from the other configuration leaked through the filter.
    assert returned <= live_ids

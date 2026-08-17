"""Stored embeddings carry the configuration that produced them (#1546).

`model_name` names the model, not the vector space. The space is a function of
the model, the width it was asked for AND the endpoint that served it, so one
model behind two endpoints is two spaces under one label. Semantic search
embeds the query with the configuration live at query time and filtered stored
rows by model name alone, which let it compare vectors across spaces: cosine
distances came back well-formed and meaningless, nothing errored, and ranking
quality degraded silently.

Every row now carries `config_fingerprint`, the SHA-256 of that triple, stamped
from the configuration the writing run PINNED. Readers filter on it.

A row with no stamp predates the column. It is matched on model name alone,
exactly as before, so an upgrade neither empties semantic search nor triggers a
catalog-wide re-embed. `test_a_legacy_unstamped_row_*` are the tests that hold
that guarantee down, and each has a counterfactual named in its docstring.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (including pgvector)
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.db.models import AppSetting
from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
from app.modules.admin.service import AdminService
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.extensions.defaults_processing_port import DefaultProcessingPort
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import helpers
from app.processing.embeddings import service as service_module
from app.processing.embeddings.helpers import (
    embedding_config_fingerprint,
    resolve_embedding_config_fingerprint,
)
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import resolve_embedding_base_url

from tests.factories import create_dataset, get_user_id

_DIMS = 1536
_MODEL = "stamp-1546-model"
# A second configuration differing ONLY in the endpoint. Same model name, same
# width — which is exactly the case `model_name` cannot tell apart.
_FOREIGN_URL = "https://embeddings-elsewhere.invalid/v1"


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Clear the two process-global caches these tests read through.

    `has_embeddings` (TTL 30s) decides whether the vector arm runs at all, and
    a False cached by an earlier test starves it. The query-embedding LRU is
    keyed on the configuration fingerprint now, so a leftover entry cannot be
    served across configurations — but clearing it keeps the provider-call
    counts in these tests about this test.
    """
    from app.modules.catalog.search import service_semantic

    helpers._has_embeddings_cache.clear()
    service_semantic._embedding_cache_clear()
    yield
    helpers._has_embeddings_cache.clear()
    service_semantic._embedding_cache_clear()


@pytest.fixture
async def restore_embedding_config(test_db_session):
    """Put the AI config back; the worker database is shared across tests."""
    before = (
        await EMBEDDING_MODEL.get(test_db_session),
        await EMBEDDING_DIMS.get(test_db_session),
    )
    yield
    await EMBEDDING_MODEL.set(test_db_session, before[0])
    await EMBEDDING_DIMS.set(test_db_session, before[1])


async def _live_and_foreign(session, *, model_name: str) -> tuple[str, str]:
    """Two configuration fingerprints: the live one, and one from elsewhere.

    Both are built from `embedding_config_fingerprint` over a (model, width,
    endpoint) triple, so neither comes out of the resolver under test. The live
    one is that function applied to the endpoint the provider actually resolves
    to; the foreign one differs in the endpoint alone.
    """
    dimensions = await EMBEDDING_DIMS.get(session)
    live_url = await resolve_embedding_base_url(session)
    assert live_url != _FOREIGN_URL
    return (
        embedding_config_fingerprint(model_name, dimensions, live_url),
        embedding_config_fingerprint(model_name, dimensions, _FOREIGN_URL),
    )


def _vector_band(base_value: float, *, lo: int = 900) -> list[float]:
    """A unit vector whose signal sits in dims [lo, lo+10) and zeros elsewhere.

    Orthogonal to the bands the other search suites use, so a query built here
    matches only the rows this file writes, whatever else the shared worker
    database is carrying.
    """
    vec = [0.0] * _DIMS
    for i in range(lo, lo + 10):
        vec[i] = base_value + ((i - lo) * 0.01)
    magnitude = sum(v * v for v in vec) ** 0.5
    return [v / magnitude for v in vec]


async def _add_embedding(
    session,
    record_id: uuid.UUID,
    *,
    model_name: str,
    config_fingerprint: str | None,
    vector: list[float] | None = None,
) -> None:
    session.add(
        RecordEmbedding(
            record_id=record_id,
            embedding=vector or ([1.0] + [0.0] * (_DIMS - 1)),
            model_name=model_name,
            config_fingerprint=config_fingerprint,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await session.commit()


async def _create_dataset(session, *, created_by: uuid.UUID, name: str) -> Dataset:
    """A published, public Record+Dataset pair the search endpoint can return."""
    record = Record(
        title=name,
        summary=f"Summary for {name}",
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _enable_semantic_search(session) -> None:
    existing = (
        await session.execute(
            select(AppSetting).where(AppSetting.key == "semantic_search_enabled")
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(AppSetting(key="semantic_search_enabled", value={"v": True}))
    else:
        existing.value = {"v": True}
    await session.commit()

    from app.platform.cache import get_cache

    try:
        await get_cache().delete("config:semantic_search_enabled")
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# The fingerprint itself
# ---------------------------------------------------------------------------


def test_the_fingerprint_separates_every_component_of_the_vector_space():
    """Model, width and endpoint each move it, and it is stable across calls."""
    base = embedding_config_fingerprint("model-a", 1536, "https://a.invalid/v1")

    assert base == embedding_config_fingerprint("model-a", 1536, "https://a.invalid/v1")
    assert base != embedding_config_fingerprint("model-b", 1536, "https://a.invalid/v1")
    assert base != embedding_config_fingerprint("model-a", 768, "https://a.invalid/v1")
    # The endpoint alone. This is the pair `model_name` cannot distinguish and
    # the reason the column exists.
    assert base != embedding_config_fingerprint("model-a", 1536, "https://b.invalid/v1")


def test_an_unset_endpoint_is_not_the_string_none_and_not_empty():
    """`None` is a resolved value the provider interface permits (see #1525).

    A delimiter join would collapse it into `"None"` or `""`, so a provider
    answering "use the client default" would share an identity with one pointed
    at a host literally named that. JSON keeps the three apart.
    """
    stamps = {
        embedding_config_fingerprint("m", 1536, None),
        embedding_config_fingerprint("m", 1536, "None"),
        embedding_config_fingerprint("m", 1536, ""),
    }
    assert len(stamps) == 3


def test_a_component_boundary_cannot_be_forged_from_inside_a_value():
    """("a|b", None) must not collide with ("a", "b")-style neighbours."""
    assert embedding_config_fingerprint('a","b', 1536, None) != (
        embedding_config_fingerprint("a", 1536, "b")
    )


@pytest.mark.anyio
async def test_an_unresolvable_configuration_answers_with_a_sentinel(test_db_session):
    """A reader must degrade, not raise, and must match no STAMPED row.

    The endpoint resolves through the provider extension, which raises whenever
    the database endpoint diverges from the operator-approved environment URL.
    Search consults this only to be careful; turning that into a 500 would take
    search down over it.
    """
    with patch.object(
        service_module,
        "get_embedding_provider",
        side_effect=RuntimeError("provider is unreachable"),
    ):
        answer = await resolve_embedding_config_fingerprint(test_db_session)

    assert answer == helpers.UNKNOWN_EMBEDDING_CONFIG
    # Not a hex digest, so it can never equal a real fingerprint.
    assert answer != embedding_config_fingerprint(_MODEL, _DIMS, None)


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_search_excludes_a_row_from_a_foreign_configuration(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """The defect: one model, two endpoints, one label, cross-space matches.

    Both rows carry the ACTIVE model name and near-identical vectors. One was
    written under the live configuration and one under another endpoint's. Only
    the first is comparable against a query vector the live configuration
    produced; the second is a different space and its cosine distance means
    nothing.
    """
    session = test_db_session
    await _enable_semantic_search(session)
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)
    live, foreign = await _live_and_foreign(session, model_name=model_name)

    # Titles share no lexical content with the query below, so anything that
    # comes back came back through the vector arm.
    kept = await _create_dataset(session, created_by=user_id, name="Zqx Stamp Kept")
    dropped = await _create_dataset(
        session, created_by=user_id, name="Zqx Stamp Dropped"
    )
    await _add_embedding(
        session,
        kept.record_id,
        model_name=model_name,
        config_fingerprint=live,
        vector=_vector_band(1.0),
    )
    await _add_embedding(
        session,
        dropped.record_id,
        model_name=model_name,
        config_fingerprint=foreign,
        vector=_vector_band(0.98),
    )

    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=_vector_band(1.0),
    ):
        response = await client.get(
            "/search/datasets/",
            params={"q": "unrelated lexical query text"},
            headers=admin_auth_header,
        )

    assert response.status_code == 200
    titles = [f["properties"]["title"] for f in response.json()["features"]]
    # Non-vacuity: the vector arm ran and returned the row it should.
    assert "Zqx Stamp Kept" in titles
    assert "Zqx Stamp Dropped" not in titles


@pytest.mark.anyio
async def test_the_match_total_excludes_a_foreign_configuration_too(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """numberMatched is a second, independently written filter over the table.

    `_run_rrf_merge` counts vector-only matches with its own query rather than
    from the ranks, so a fix applied to the ranking predicate alone would report
    a total that counts rows no page can ever show — a `next` link onto an
    empty page.
    """
    session = test_db_session
    await _enable_semantic_search(session)
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)
    live, foreign = await _live_and_foreign(session, model_name=model_name)

    for index, fingerprint in ((0, live), (1, foreign), (2, foreign)):
        dataset = await _create_dataset(
            session, created_by=user_id, name=f"Zqy Stamp Total {index}"
        )
        await _add_embedding(
            session,
            dataset.record_id,
            model_name=model_name,
            config_fingerprint=fingerprint,
            vector=_vector_band(1.0 - index * 0.01, lo=920),
        )

    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=_vector_band(1.0, lo=920),
    ):
        response = await client.get(
            "/search/datasets/",
            params={"q": "unrelated lexical query text"},
            headers=admin_auth_header,
        )

    assert response.status_code == 200
    body = response.json()
    titles = [f["properties"]["title"] for f in body["features"]]
    assert "Zqy Stamp Total 0" in titles
    assert body["numberMatched"] == 1


@pytest.mark.anyio
async def test_a_legacy_unstamped_row_stays_searchable_after_upgrade(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """The upgrade guarantee: day one after migrating, search still works.

    Every row already in the table has no stamp, and what configuration
    produced it is not recoverable. Filtering them out would empty semantic
    search until a full regenerate finished; stamping them with today's
    configuration in the migration would invent provenance. They are
    grandfathered instead, on model name alone.

    Counterfactual: drop the `config_fingerprint IS NULL` arm of
    `RecordEmbedding.usable_by_config` and this fails while every other test in
    this file still passes.
    """
    session = test_db_session
    await _enable_semantic_search(session)
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)

    legacy = await _create_dataset(session, created_by=user_id, name="Zqz Stamp Legacy")
    await _add_embedding(
        session,
        legacy.record_id,
        model_name=model_name,
        config_fingerprint=None,
        vector=_vector_band(1.0, lo=940),
    )

    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=_vector_band(1.0, lo=940),
    ):
        response = await client.get(
            "/search/datasets/",
            params={"q": "unrelated lexical query text"},
            headers=admin_auth_header,
        )

    assert response.status_code == 200
    titles = [f["properties"]["title"] for f in response.json()["features"]]
    assert "Zqz Stamp Legacy" in titles


# ---------------------------------------------------------------------------
# The non-force backfill's "already covered" decision
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_foreign_stamped_row_does_not_count_as_coverage(test_db_session):
    """Generate Missing has to see what search cannot use.

    Leaving the stamp out of this predicate relocates #1546 into the skip
    decision: the panel reports the catalog covered, Generate Missing does
    nothing, and the vector arm matches none of it.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)
    live, foreign = await _live_and_foreign(session, model_name=model_name)

    covered = await create_dataset(
        session, created_by=user_id, name="Stamp Scope Covered"
    )
    stale = await create_dataset(session, created_by=user_id, name="Stamp Scope Stale")
    await _add_embedding(
        session, covered.record_id, model_name=model_name, config_fingerprint=live
    )
    await _add_embedding(
        session, stale.record_id, model_name=model_name, config_fingerprint=foreign
    )

    missing = {
        record.id
        for record in await DefaultProcessingPort().get_records_without_embeddings(
            session, force=False
        )
    }

    assert stale.record_id in missing
    # Non-vacuity: the predicate did not simply select everything.
    assert covered.record_id not in missing


@pytest.mark.anyio
async def test_a_legacy_unstamped_row_is_not_offered_for_re_embedding(test_db_session):
    """Upgrading must not queue a catalog-wide re-embed nobody asked to pay for.

    An unstamped row is what every instance has on the morning after the
    migration. Treating it as missing would make the next Generate Missing bill
    the operator for the whole catalog at provider rates.

    Counterfactual: same as the search test — remove the NULL arm from
    `usable_by_config` and this record reads as missing.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)

    legacy = await create_dataset(
        session, created_by=user_id, name="Stamp Scope Legacy"
    )
    await _add_embedding(
        session, legacy.record_id, model_name=model_name, config_fingerprint=None
    )

    missing = {
        record.id
        for record in await DefaultProcessingPort().get_records_without_embeddings(
            session, force=False
        )
    }
    assert legacy.record_id not in missing


@pytest.mark.anyio
async def test_an_unresolvable_configuration_selects_nothing(
    test_db_session, monkeypatch
):
    """Fail closed, one value out from the unresolvable-model branch (#1506).

    Every stamped row reads as foreign when the configuration cannot be
    resolved, so the alternative is handing the whole catalog to a run whose
    provider call is the thing that cannot be resolved: every record embedded
    at provider cost, every insert failing.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    await create_dataset(session, created_by=user_id, name="Stamp Scope Unresolvable")

    async def _unresolvable(_session, *, model_name=None):
        return helpers.UNKNOWN_EMBEDDING_CONFIG

    monkeypatch.setattr(helpers, "resolve_embedding_config_fingerprint", _unresolvable)
    records = await DefaultProcessingPort().get_records_without_embeddings(
        session, force=False
    )
    assert records == []


@pytest.mark.anyio
async def test_re_embedding_a_foreign_stamped_row_replaces_it(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """The row is keyed (record_id, model_name), so the replacement is an UPDATE.

    Once a foreign-stamped row is offered as missing, a plain INSERT answers it
    with a unique violation instead of a vector — the bug the ON CONFLICT DO
    UPDATE closes. Afterwards the record holds ONE row for the model, stamped
    with the configuration the run pinned.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)
    live, foreign = await _live_and_foreign(session, model_name=_MODEL)

    dataset = await create_dataset(session, created_by=user_id, name="Stamp Replace DS")
    await _add_embedding(
        session, dataset.record_id, model_name=_MODEL, config_fingerprint=foreign
    )

    async def _fake_batch(texts, _session, *, model, dimensions, base_url):
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    monkeypatch.setattr(backfill_module, "generate_embeddings_batch", _fake_batch)
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="stamp-test-key")
    )

    await backfill_module.backfill_embeddings(session, force=False)

    rows = (
        (
            await session.execute(
                select(RecordEmbedding.config_fingerprint).where(
                    RecordEmbedding.record_id == dataset.record_id,
                    RecordEmbedding.model_name == _MODEL,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [live]


@pytest.mark.anyio
async def test_the_stamp_comes_from_the_pin_not_from_a_read_at_write_time(
    test_db_session,
    restore_embedding_config,
    monkeypatch,
):
    """The endpoint half has to be the one the vector was actually made against.

    A run pins (model, width, endpoint) and hands that triple to every provider
    call. Stamping from a fresh read at write time would name whatever the
    configuration says by then, which is provenance the run did not observe.

    The state that separates the two is real and is #1551's residue: an
    endpoint edit that makes the provider's resolve RAISE. `_pinned_config_drift`
    deliberately does not treat that as drift — for the shipped provider it is
    what an endpoint diverging from the operator-approved environment URL looks
    like, and it says nothing about where vectors are going — so the run carries
    on, correctly, under the pin. A writer that re-read would get the
    unresolvable-configuration sentinel and stamp rows nothing can ever match.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    await EMBEDDING_MODEL.set(session, _MODEL)
    await EMBEDDING_DIMS.set(session, _DIMS)
    dataset = await create_dataset(session, created_by=user_id, name="Stamp Pin DS")
    pinned_url = await resolve_embedding_base_url(session)

    class _EndpointBreaksMidRun:
        """Resolves normally until the pin is taken, then refuses.

        Three resolutions precede the batch loop on the non-force path: one for
        the selection's fingerprint, then the snapshot's capture and its
        re-read. From the fourth on, the endpoint no longer resolves.
        """

        def __init__(self):
            self.resolves = 0

        async def resolve_runtime_config(self, _session):
            self.resolves += 1
            if self.resolves > 3:
                raise RuntimeError("endpoint no longer resolves")
            return {
                "default_model": _MODEL,
                "default_dims": _DIMS,
                "base_url": pinned_url,
            }

        async def embed(self, *, texts, model, dimensions, base_url, timeout):
            return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]

    provider = _EndpointBreaksMidRun()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="stamp-test-key")
    )

    result = await backfill_module.backfill_embeddings(session, force=False)

    # Non-vacuity: the run reached the batch loop and the endpoint really did
    # stop resolving before the rows were written.
    assert result["created"] > 0
    assert provider.resolves > 3
    assert (
        await resolve_embedding_config_fingerprint(session, model_name=_MODEL)
        == helpers.UNKNOWN_EMBEDDING_CONFIG
    )

    stamp = (
        await session.execute(
            select(RecordEmbedding.config_fingerprint).where(
                RecordEmbedding.record_id == dataset.record_id,
                RecordEmbedding.model_name == _MODEL,
            )
        )
    ).scalar_one()
    assert stamp == embedding_config_fingerprint(_MODEL, _DIMS, pinned_url)


# ---------------------------------------------------------------------------
# Admin coverage stats
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_coverage_counts_only_rows_the_live_configuration_can_use(
    test_db_session,
):
    """A coverage bar over vectors the vector arm skips is #1503 all over again."""
    session = test_db_session
    service = AdminService(session)
    baseline = await service.get_embedding_stats()

    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)
    live, foreign = await _live_and_foreign(session, model_name=model_name)

    covered = await create_dataset(
        session, created_by=user_id, name="Stamp Stats Covered"
    )
    stale = await create_dataset(session, created_by=user_id, name="Stamp Stats Stale")
    await _add_embedding(
        session, covered.record_id, model_name=model_name, config_fingerprint=live
    )
    await _add_embedding(
        session, stale.record_id, model_name=model_name, config_fingerprint=foreign
    )

    after = await service.get_embedding_stats()
    assert after.total_records == baseline.total_records + 2
    # Only the live-configuration row counts as covered.
    assert after.embedded_records == baseline.embedded_records + 1
    assert after.missing_records == baseline.missing_records + 1
    # And the foreign one is visible as stale rather than absent, which is what
    # tells an operator to run Generate Missing.
    assert after.stale_records == baseline.stale_records + 1


@pytest.mark.anyio
async def test_coverage_agrees_with_what_search_can_retrieve(test_db_session):
    """Two spellings of one rule, pinned against each other.

    `AdminService.get_embedding_stats` writes the condition as raw SQL while
    semantic search and the backfill selection apply
    `RecordEmbedding.usable_by_config`. Drift between them is the exact class of
    bug this PR is about, so it is not left to inspection: every combination of
    model and stamp goes in, and the count the panel reports has to equal the
    number of rows the ORM predicate selects.
    """
    session = test_db_session
    user_id = await get_user_id(session, "admin")
    model_name = await EMBEDDING_MODEL.get(session)
    live, foreign = await _live_and_foreign(session, model_name=model_name)

    combinations = [
        (model_name, live),
        (model_name, foreign),
        (model_name, None),
        ("stamp-1546-other-model", live),
        ("stamp-1546-other-model", foreign),
        ("stamp-1546-other-model", None),
    ]
    for index, (row_model, fingerprint) in enumerate(combinations):
        dataset = await create_dataset(
            session, created_by=user_id, name=f"Stamp Agreement {index}"
        )
        await _add_embedding(
            session,
            dataset.record_id,
            model_name=row_model,
            config_fingerprint=fingerprint,
        )

    panel_count = (
        await session.execute(
            text(
                "SELECT COUNT(DISTINCT visible_record.id) "
                "FILTER (WHERE embedding.model_name = :model_name "
                "AND (embedding.config_fingerprint IS NULL "
                "OR embedding.config_fingerprint = :config_fingerprint)) "
                "FROM catalog.records AS visible_record "
                "LEFT JOIN catalog.record_embeddings AS embedding "
                "ON embedding.record_id = visible_record.id"
            ),
            {"model_name": model_name, "config_fingerprint": live},
        )
    ).scalar_one()

    orm_count = (
        await session.execute(
            select(func.count(func.distinct(RecordEmbedding.record_id)))
            .select_from(RecordEmbedding)
            .join(Record, RecordEmbedding.record_id == Record.id)
            .where(RecordEmbedding.usable_by_config(model_name, live))
        )
    ).scalar_one()

    assert panel_count == orm_count
    # Non-vacuity: the fixture really did contain rows the rule has to reject.
    total_rows = (
        await session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one()
    assert total_rows > orm_count

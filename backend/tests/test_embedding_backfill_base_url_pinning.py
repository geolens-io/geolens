"""One backfill run must reach one endpoint (#1525).

Follow-up to #1511/#1519, which pinned the model and the dimensions for the
length of a run. `base_url` was left re-reading per provider call: every
`generate_embeddings_batch` call asked the provider extension to
`resolve_runtime_config` again, so an endpoint edit landing mid-run changed
where later batches went while the rows kept the label the run pinned.

Two scenarios, because the shipped provider and an extension provider fail
differently on the same edit.

`_EndpointRecordingProvider` is an extension that resolves its own endpoint
from configuration, which is all `EmbeddingProviderExtension` asks of it. There
the edit splits the run across two endpoints, which is the corruption #1525
describes: same `model_name` label, vectors from two vector spaces.

`_BoundEndpointProvider` delegates to the shipped
`DefaultOpenAIEmbeddingProvider.resolve_runtime_config`, so the real credential
binding runs. That binding (`app/core/ai_credentials.py`) refuses to point the
environment-provided API key at a database-supplied endpoint, so the shipped
provider cannot be redirected — it raises instead. Every batch after the edit
therefore fails, is retried per record, fails again, and lands in `errors`. The
run reaches one endpoint and abandons the rest of the catalog.

The edit is driven through the real `PersistentConfig.set`, from inside the
first provider call — the run spends its time there, so that is where an admin
edit realistically lands, and it is after the snapshot has captured its values.
Both paths are covered: the divergence is identical on force and non-force,
exactly as it was for the model in #1519.

The remaining tests cover the other windows a run has to survive, in the order
they were found:

- An edit landing *inside* the snapshot, which the run refuses rather than pins.
- An edit changing model and endpoint together, which is why all three values
  are captured and compared as one unit instead of one window per value
  (#1525 review, codex P1).
- An endpoint that resolves to `None`, which is a pin and not an omission
  (#1525 review, codex P2).
- Two cache windows (#1525 review r2, codex P1). `update_settings` commits the
  whole batch and then evicts each key in turn, so between the commit and the
  last eviction a cached read can be stale. With one key evicted the snapshot
  could pin a MIXED pair; with none evicted it could pin a wholly SUPERSEDED
  one. Both are invisible to a comparison of cached reads, because two reads
  through the same stale entry agree, which is why the snapshot reads uncached.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from app.core import ai_credentials
from app.core.persistent_config import (
    EMBEDDING_BASE_URL,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
)
from app.platform.extensions.defaults_ai_openai import DefaultOpenAIEmbeddingProvider
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings import service as service_module
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_MODEL = "endpoint-pin-model"
_MODEL_AFTER = "endpoint-pin-model-after"
# Matches the fixed vector column, so every row this run writes still inserts
# and the assertions stay on the endpoint rather than on storage.
_DIMS = 1536
# Different enough to be visible in an assertion; the fake provider answers at
# _DIMS whatever it is asked for, so the row still inserts.
_DIMS_AFTER = 768
# Canonical already (no trailing slash, lowercase host, no query): the shipped
# provider canonicalizes what it returns, and a non-canonical literal here would
# make the comparison fail for a reason that is not the finding.
_URL_A = "https://embeddings-a.invalid/v1"
_URL_B = "https://embeddings-b.invalid/v1"


class _EndpointRecordingProvider:
    """An extension provider that resolves its endpoint from configuration.

    Records what each call received, and lands the admin's endpoint edit during
    the first provider call.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._session = None
        self._edited = False

    async def resolve_runtime_config(self, session):
        self._session = session
        return {
            "default_model": "provider-fallback-model",
            "default_dims": _DIMS,
            "base_url": await EMBEDDING_BASE_URL.get(session),
        }

    async def _land_the_admin_edit(self) -> None:
        """Repoint the embedding endpoint, once, through the real setter."""
        if self._edited or self._session is None:
            return
        self._edited = True
        await EMBEDDING_BASE_URL.set(self._session, _URL_B)

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append(
            {"model": model, "dimensions": dimensions, "base_url": base_url}
        )
        await self._land_the_admin_edit()
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]


class _BoundEndpointProvider(_EndpointRecordingProvider):
    """Resolves through the shipped provider, credential binding included.

    `DefaultOpenAIEmbeddingProvider.resolve_runtime_config` runs
    `bind_openai_credential_base_url`, which refuses a database endpoint that
    differs from the operator-approved environment one. So this provider cannot
    be redirected by the edit; it raises for every call made after it.
    """

    async def resolve_runtime_config(self, session):
        self._session = session
        return await DefaultOpenAIEmbeddingProvider().resolve_runtime_config(session)


class _SnapshotWindowProvider(_EndpointRecordingProvider):
    """Repoints the endpoint from inside the snapshot's first resolve.

    Returns the pre-edit value from that call, so the snapshot's second read
    sees a different endpoint — the window the comparison exists to catch.
    """

    async def resolve_runtime_config(self, session):
        self._session = session
        current = await EMBEDDING_BASE_URL.get(session)
        await self._land_the_admin_edit()
        return {
            "default_model": "provider-fallback-model",
            "default_dims": _DIMS,
            "base_url": current,
        }


class _AtomicSwitchProvider(_EndpointRecordingProvider):
    """Repoints model AND endpoint together, from inside the first resolve.

    fix(#1525 review, codex P1). An admin who changes both in one PUT is the
    case a per-value guard cannot see: with the endpoint captured in a window
    of its own, after the model had already been compared, the model comparison
    passed on the old value and the endpoint comparison saw the new one twice,
    so the run pinned old-model-plus-new-endpoint. That pairing never existed
    in config, and if the new endpoint happens to accept the old model nothing
    downstream rejects it.

    Returning the post-edit endpoint from this very call is what makes the two
    implementations distinguishable: a split window agrees with itself, and a
    single window over all three sees the model move.
    """

    async def resolve_runtime_config(self, session):
        self._session = session
        if not self._edited:
            self._edited = True
            await EMBEDDING_MODEL.set(session, _MODEL_AFTER)
            await EMBEDDING_BASE_URL.set(session, _URL_B)
        return {
            "default_model": "provider-fallback-model",
            "default_dims": _DIMS,
            "base_url": await EMBEDDING_BASE_URL.get(session),
        }


class _QuietRecordingProvider:
    """Records what each call received and changes nothing.

    The cache tests are about what the SNAPSHOT observed, so the provider must
    not also be editing config underneath them.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def resolve_runtime_config(self, session):
        return {
            "default_model": "provider-fallback-model",
            "default_dims": _DIMS,
            "base_url": await EMBEDDING_BASE_URL.get(session),
        }

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append(
            {"model": model, "dimensions": dimensions, "base_url": base_url}
        )
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]


class _NullEndpointProvider:
    """Resolves its endpoint to None, which the provider interface permits.

    fix(#1525 review, codex P2). `None` is a resolved value, not an omission,
    so a run that snapshots it has pinned something. Counting resolves is what
    shows whether the pin held: a gate testing `base_url is None` reads the pin
    as absent and re-resolves per batch.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.resolves = 0

    async def resolve_runtime_config(self, session):
        self.resolves += 1
        return {
            "default_model": "provider-fallback-model",
            "default_dims": _DIMS,
            "base_url": None,
        }

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append({"model": model, "base_url": base_url})
        return [[1.0] + [0.0] * (_DIMS - 1) for _ in texts]


@pytest.fixture
async def restore_embedding_config(test_db_session):
    """Put the AI config back; the worker DB is shared across tests."""
    before = (
        await EMBEDDING_MODEL.get(test_db_session),
        await EMBEDDING_DIMS.get(test_db_session),
        await EMBEDDING_BASE_URL.get(test_db_session),
    )
    yield
    await EMBEDDING_MODEL.set(test_db_session, before[0])
    await EMBEDDING_DIMS.set(test_db_session, before[1])
    await EMBEDDING_BASE_URL.set(test_db_session, before[2])


async def _seed_two_records(session, label: str) -> None:
    """Two embeddable records, so the run makes more than one provider call."""
    user_id = await get_user_id(session, "admin")
    await create_dataset(session, created_by=user_id, name=f"{label} One")
    await create_dataset(session, created_by=user_id, name=f"{label} Two")


@pytest.mark.anyio
@pytest.mark.parametrize("force", [True, False], ids=["force", "non_force"])
async def test_a_mid_run_endpoint_edit_cannot_split_a_run_across_providers(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
    force,
):
    """Every vector a run stores must come from the endpoint it resolved."""
    await _seed_two_records(test_db_session, f"Endpoint Pinning {force}")

    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    provider = _EndpointRecordingProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )
    # One record per provider call. The edit lands during the first call, so
    # the run needs a second one for it to be in front of — and at the default
    # batch size of 128 the non-force path makes exactly one.
    monkeypatch.setattr(backfill_module, "_BATCH_SIZE", 1)

    # fix(#1525 review r4, codex P2): the run STOPS at the next batch boundary
    # once the endpoint it pinned is no longer the active one, instead of
    # quietly finishing the catalog in a vector space the live search will
    # never match. So "one run reached two endpoints" is now unreachable rather
    # than merely avoided — the guard prevents the second call, it does not
    # make the second call use the right value.
    #
    # Which means this test no longer covers the pin ITSELF: with the
    # `base_url=` argument removed from the batch calls, the first batch would
    # re-resolve, still get _URL_A because the edit has not landed yet, and the
    # run would stop at the same boundary with the same observables. The pin is
    # covered by `test_an_endpoint_that_resolves_to_none_is_still_pinned`,
    # which counts resolves and so sees a batch resolving a value for itself.
    stopped = False
    try:
        await backfill_module.backfill_embeddings(test_db_session, force=force)
    except RuntimeError:
        stopped = True

    # Non-vacuity, both halves. No provider call means no argument to compare,
    # and the edit never landing means there was no switch to survive.
    assert provider.calls, "the provider was never called"
    assert await EMBEDDING_BASE_URL.get(test_db_session) == _URL_B, (
        "the admin edit never landed"
    )

    # The finding itself: every vector this run produced came from the endpoint
    # it resolved, never from the one the config moved to.
    assert {call["base_url"] for call in provider.calls} == {_URL_A}
    assert stopped


@pytest.mark.anyio
@pytest.mark.parametrize("force", [True, False], ids=["force", "non_force"])
async def test_a_mid_run_endpoint_edit_does_not_abandon_the_rest_of_the_catalog(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
    force,
):
    """The shipped provider's version of the same edit.

    Credential binding stops the endpoint from moving, so the damage is not a
    mislabelled vector — it is a run that resolves the config again per call
    and raises from the second call onward. Each batch fails, is retried per
    record, fails again, and counts as an error, so an edit that a pinned run
    would not even notice costs the whole remainder of the catalog.
    """
    await _seed_two_records(test_db_session, f"Endpoint Binding {force}")

    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    provider = _BoundEndpointProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )
    # The binding compares the database endpoint against the operator-approved
    # environment one, so the environment has to name _URL_A for the run to
    # start at all, and an API key has to be present for the check to run.
    monkeypatch.setattr(
        ai_credentials,
        "settings",
        SimpleNamespace(
            openai_api_key="pin-test-key",
            embedding_base_url=_URL_A,
            openai_base_url=None,
        ),
    )
    monkeypatch.setattr(backfill_module, "_BATCH_SIZE", 1)

    result = await backfill_module.backfill_embeddings(test_db_session, force=force)

    # The damage first: an unpinned run fails here showing the records it gave
    # up on, which is the finding. The call-count guard below would otherwise
    # fire first and report the symptom (no second call) instead.
    assert result["errors"] == 0
    assert result["created"] >= 2
    assert await EMBEDDING_BASE_URL.get(test_db_session) == _URL_B, (
        "the admin edit never landed"
    )

    # Non-vacuity for the endpoint comparison: one call is not a comparison.
    assert len(provider.calls) >= 2, "the run made fewer than two provider calls"
    assert {call["base_url"] for call in provider.calls} == {_URL_A}


@pytest.mark.anyio
@pytest.mark.parametrize("force", [True, False], ids=["force", "non_force"])
async def test_an_edit_inside_the_snapshot_window_aborts_the_run(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
    force,
):
    """An endpoint that moves while the run is starting is refused, not pinned.

    The tests above flip the endpoint once the snapshot has already captured
    it, which is what pinning is for. This one lands the edit *inside* the
    capture, where there is no single value to pin: the run would otherwise
    commit to an endpoint config no longer names. The snapshot resolves twice
    and compares, and on the force path it does so ahead of the DELETE, so an
    abort has to leave existing vectors alone.
    """
    await _seed_two_records(test_db_session, f"Endpoint Snapshot {force}")
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    # A row to lose, so the force path's survival is observable.
    user_id = await get_user_id(test_db_session, "admin")
    seeded = await create_dataset(
        test_db_session, created_by=user_id, name=f"Endpoint Snapshot Seed {force}"
    )
    test_db_session.add(
        RecordEmbedding(
            record_id=seeded.record_id,
            embedding=[1.0] + [0.0] * (_DIMS - 1),
            model_name=_MODEL,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await test_db_session.commit()
    before = (
        await test_db_session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one()
    assert before > 0

    provider = _SnapshotWindowProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )

    aborted = False
    try:
        await backfill_module.backfill_embeddings(test_db_session, force=force)
    except RuntimeError:
        aborted = True

    # Checked before the abort flag: an unguarded tree fails on the vectors it
    # destroyed and the endpoint it used, which is the damage, not the missing
    # raise.
    assert provider.calls == []
    assert (
        await test_db_session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one() == before
    assert aborted
    # Non-vacuity: without the edit actually landing there was no change for
    # the comparison to catch, and the run would have aborted for some other
    # reason or not at all.
    assert await EMBEDDING_BASE_URL.get(test_db_session) == _URL_B


@pytest.mark.anyio
@pytest.mark.parametrize("force", [True, False], ids=["force", "non_force"])
async def test_an_atomic_model_and_endpoint_swap_cannot_pin_a_mixed_pair(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
    force,
):
    """Both values move together, so the snapshot has to look at both again.

    fix(#1525 review, codex P1): the values are pinned as a unit, so they have
    to be verified as a unit. Capturing and comparing the endpoint separately,
    after the model had already been compared, left a gap between the two
    comparisons that a single PUT changing model and endpoint together lands
    in. The pinned result is the old model against the new endpoint, which no
    admin ever chose, and nothing downstream can tell: the model still names a
    real model and the endpoint still names a real endpoint.

    On the force path the snapshot runs ahead of the DELETE, so the abort also
    has to leave the existing vectors alone.
    """
    await _seed_two_records(test_db_session, f"Atomic Swap {force}")
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    user_id = await get_user_id(test_db_session, "admin")
    seeded = await create_dataset(
        test_db_session, created_by=user_id, name=f"Atomic Swap Seed {force}"
    )
    test_db_session.add(
        RecordEmbedding(
            record_id=seeded.record_id,
            embedding=[1.0] + [0.0] * (_DIMS - 1),
            model_name=_MODEL,
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await test_db_session.commit()
    before = (
        await test_db_session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one()
    assert before > 0

    provider = _AtomicSwitchProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )

    aborted = False
    try:
        await backfill_module.backfill_embeddings(test_db_session, force=force)
    except RuntimeError:
        aborted = True

    # Checked first: a tree that pins the mixed pair fails here, on the vectors
    # it went on to write from an endpoint the run never validated the model
    # against. That is the damage; the missing raise is only how it happened.
    assert provider.calls == []
    assert (
        await test_db_session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one() == before
    assert aborted
    # Non-vacuity: both halves have to have actually moved, or there was no
    # mixed pair available to pin and the run aborted for some other reason.
    assert await EMBEDDING_MODEL.get(test_db_session) == _MODEL_AFTER
    assert await EMBEDDING_BASE_URL.get(test_db_session) == _URL_B


@pytest.mark.anyio
async def test_an_endpoint_that_resolves_to_none_is_still_pinned(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
):
    """A resolved None is a pin, not an omission.

    fix(#1525 review, codex P2): the provider interface lets an extension
    answer `{"base_url": None}`, meaning "use the client default". Testing
    `base_url is None` to decide whether the caller pinned anything reads that
    as an omission and resolves the live config again on every batch, so the
    providers most likely to have an unusual endpoint config are exactly the
    ones the pin stops protecting.

    Resolve calls are the observable. The snapshot makes two, to capture and to
    compare; a batch loop that adds one per batch is the bug.
    """
    await _seed_two_records(test_db_session, "Null Endpoint")
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)

    provider = _NullEndpointProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )
    monkeypatch.setattr(backfill_module, "_BATCH_SIZE", 1)

    await backfill_module.backfill_embeddings(test_db_session, force=False)

    # Non-vacuity: with fewer than two batches there is no per-batch growth to
    # detect, and the count below would hold on the unfixed tree too.
    assert len(provider.calls) >= 2, "the run made fewer than two provider calls"
    # Two for `_snapshot_embedding_config` (capture then re-read), plus exactly
    # one per batch for the drift check added by #1525 review r4. A batch that
    # resolved the config for its own VALUE as well would add a second per
    # batch, which is the bug: with `base_url is None` as the pin test, a
    # resolved None reads as an omission and every batch re-resolves.
    assert provider.resolves == 2 + len(provider.calls)
    # And the pinned value actually reached the provider as itself.
    assert {call["base_url"] for call in provider.calls} == {None}


@pytest.mark.anyio
async def test_a_half_evicted_cache_cannot_pin_a_mixed_pair(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
):
    """Two reads through one stale cache entry agree with each other.

    fix(#1525 review r2, codex P1): `PersistentConfig.get` answers from a
    PER-KEY cache, and `update_settings` commits the whole batch before evicting
    each key in turn (settings/router.py:338-345). Between the commit and the
    last eviction, one key answers from the DB while another answers from cache,
    so a snapshot built out of cached reads can pin the new model beside the old
    dimensions. Comparing those reads cannot see it: both passes hit the same
    stale entry and agree. It is the settings-window bug one layer out, a
    consistent read of an inconsistent state.

    Driven through a real `InMemoryCacheProvider`, so the read path under test
    is the production one, and the half-evicted state is built the way the
    router builds it: commit both values, then evict only one key.

    Note what is asserted. Uncached reads do not make the run abort here, they
    make it pin the committed pair, so the assertion is on the pair the
    provider received rather than on a raise. Aborting would be wrong: nothing
    is inconsistent in the database, only in the cache.
    """
    from app.core.persistent_config import _CACHE_PREFIX
    from app.platform.cache import provider as cache_provider_module
    from app.platform.cache.memory import InMemoryCacheProvider

    cache = InMemoryCacheProvider()
    monkeypatch.setattr(cache_provider_module, "_cache_provider", cache)

    await _seed_two_records(test_db_session, "Half Evicted")
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    # Warm both keys, then commit the update straight to app_settings so the
    # entries survive. `PersistentConfig.set` would evict them, which is the
    # state AFTER the window this test is about.
    assert await EMBEDDING_MODEL.get(test_db_session) == _MODEL
    assert await EMBEDDING_DIMS.get(test_db_session) == _DIMS
    await test_db_session.execute(
        text(
            "UPDATE catalog.app_settings SET value = :v WHERE key = 'embedding_model'"
        ),
        {"v": json.dumps({"v": _MODEL_AFTER})},
    )
    await test_db_session.execute(
        text("UPDATE catalog.app_settings SET value = :v WHERE key = 'embedding_dims'"),
        {"v": json.dumps({"v": _DIMS_AFTER})},
    )
    await test_db_session.commit()
    # Only the model key is evicted. This is mid-eviction, not a finished one.
    await cache.delete(f"{_CACHE_PREFIX}embedding_model")

    # Vacuity guard, and the whole premise in three lines: one key now answers
    # from the DB, the other from a stale entry, and the DB knows better. With
    # no cache provider installed these would all agree and the assertions at
    # the end would hold on the unfixed tree too.
    assert await EMBEDDING_MODEL.get(test_db_session) == _MODEL_AFTER
    assert await EMBEDDING_DIMS.get(test_db_session) == _DIMS
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _DIMS_AFTER

    provider = _EndpointRecordingProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )

    await backfill_module.backfill_embeddings(test_db_session, force=False)

    # Non-vacuity: nothing was pinned if nothing was generated.
    assert provider.calls, "the provider was never called"
    # The finding: an unfixed tree pins _MODEL_AFTER beside _DIMS, a pair that
    # was never committed together, and generates the catalog under it.
    assert {call["model"] for call in provider.calls} == {_MODEL_AFTER}
    assert {call["dimensions"] for call in provider.calls} == {_DIMS_AFTER}


@pytest.mark.anyio
async def test_a_wholly_stale_cache_cannot_pin_a_superseded_pair(
    test_db_session,
    monkeypatch,
    restore_embedding_config,
):
    """The other half of the eviction window: nothing evicted yet.

    The test above evicts one key, which is what produces a MIXED pair. This
    one evicts neither, which is the state immediately after `db.commit()` and
    before any `apply_side_effects`. Both keys then answer from cache, so the
    pair is internally consistent and simply superseded — no comparison of
    cached reads can object, because there is nothing to disagree with.

    It still corrupts a run. Every row is stamped with the pinned `model_name`,
    so a run pinned to the superseded model labels the whole catalog with a
    model that is no longer active, and semantic search reads active-model rows
    only. That is #1519's corruption reached through the cache instead of
    through a mid-run swap.

    Uncached reads see past both entries at once: `update_settings` commits the
    whole batch before evicting anything, so a read that ignores the cache gets
    the entire new batch or the entire old one, never a mixture.
    """
    from app.platform.cache import provider as cache_provider_module
    from app.platform.cache.memory import InMemoryCacheProvider

    monkeypatch.setattr(
        cache_provider_module, "_cache_provider", InMemoryCacheProvider()
    )

    await _seed_two_records(test_db_session, "Wholly Stale")
    await EMBEDDING_MODEL.set(test_db_session, _MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _DIMS)
    await EMBEDDING_BASE_URL.set(test_db_session, _URL_A)

    # Warm both, then commit both straight to app_settings and evict NOTHING.
    assert await EMBEDDING_MODEL.get(test_db_session) == _MODEL
    assert await EMBEDDING_DIMS.get(test_db_session) == _DIMS
    await test_db_session.execute(
        text(
            "UPDATE catalog.app_settings SET value = :v WHERE key = 'embedding_model'"
        ),
        {"v": json.dumps({"v": _MODEL_AFTER})},
    )
    await test_db_session.execute(
        text("UPDATE catalog.app_settings SET value = :v WHERE key = 'embedding_dims'"),
        {"v": json.dumps({"v": _DIMS_AFTER})},
    )
    await test_db_session.commit()

    # Vacuity guard: both cached reads are genuinely stale and the DB genuinely
    # moved. Warm-but-equal would make the assertions below hold on any tree.
    assert await EMBEDDING_MODEL.get(test_db_session) == _MODEL
    assert await EMBEDDING_DIMS.get(test_db_session) == _DIMS
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _MODEL_AFTER
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _DIMS_AFTER

    provider = _QuietRecordingProvider()
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "settings", SimpleNamespace(openai_api_key="pin-test-key")
    )

    await backfill_module.backfill_embeddings(test_db_session, force=False)

    assert provider.calls, "the provider was never called"
    # The run generated under the committed pair, not the cached one. The rows
    # it wrote carry this same model name, so the label names the active model.
    assert {call["model"] for call in provider.calls} == {_MODEL_AFTER}
    assert {call["dimensions"] for call in provider.calls} == {_DIMS_AFTER}

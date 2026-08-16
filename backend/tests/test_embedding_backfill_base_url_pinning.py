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

The last test covers the earlier window instead: an edit landing *inside* the
snapshot, which the run refuses rather than pins.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

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

    await backfill_module.backfill_embeddings(test_db_session, force=force)

    # Non-vacuity, both halves. With fewer than two calls there is no pair of
    # endpoints to compare and the set assertion below passes on nothing; with
    # the edit never landing there was no switch to survive in the first place.
    assert len(provider.calls) >= 2, "the run made fewer than two provider calls"
    assert await EMBEDDING_BASE_URL.get(test_db_session) == _URL_B, (
        "the admin edit never landed"
    )

    # The finding itself: one run, one endpoint, and it is the one the run
    # resolved rather than whatever the config said by the time it was called.
    assert {call["base_url"] for call in provider.calls} == {_URL_A}


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
    # Two, and only two: `_snapshot_embedding_config` captures then re-reads.
    # Anything more means a batch resolved the config for itself.
    assert provider.resolves == 2
    # And the pinned value actually reached the provider as itself.
    assert {call["base_url"] for call in provider.calls} == {None}

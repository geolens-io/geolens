"""One-request service refresh from the stored origin (#1220, ADR-002).

Five properties, and the reason each one needs a test rather than a reading of
the code:

1. **The client supplies no pointer.** The request body has one optional field
   and it is a credential. Asserted structurally as well as behaviourally,
   because "the handler ignores the URL you send" and "there is no URL to
   send" are different guarantees and only the second survives a refactor.
2. **The binding round-trips.** A refresh reads ``origin_ref``, unpacks it
   into the ingest pipeline's arguments, and the worker folds those back into
   ``origin_ref`` after the swap. If the unpack and the fold disagree, every
   refresh rewrites the pointer a little, and the drift is invisible until a
   dataset can no longer find its own source.
3. **The credential is never durable.** A token reaches the worker as a
   single-use reference and nothing else: not the task arguments, not
   ``user_metadata``, not the run row. The sentinel here is the token STRING,
   searched for in every persisted surface, because an assertion that a
   particular key is absent passes happily while the value sits under a
   different one.
4. **Admission is the same gate the re-upload door uses.** Not a similar one.
   Two admission paths is how one of them ends up missing a rule.
5. **A failed attempt cannot date a dataset it no longer describes.** The
   contact stamp is guarded on the binding the attempt actually read.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.schemas import DatasetRefreshRequest
from app.platform.dataset_origin import set_dataset_origin
from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import record_refresh_failure
from app.processing.ingest.tasks_common import resolve_service_type
from tests.factories import create_dataset as _create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_ARCGIS_BASE = "https://services.example.com/arcgis/rest/services/Parcels/FeatureServer"
_WFS_BASE = "https://services.example.com/geoserver/wfs"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _FakeCredentialBackend:
    """In-memory stand-in with an explicit expiry switch.

    TTL is driven by :meth:`expire_all` rather than by the clock: a test that
    sleeps for a real TTL is a slow test that still only proves the fake
    expires. What the suite actually needs from this class is that a claim
    REMOVES, which is asserted directly below, plus a way to reach the
    expired branch. The real ``SET NX EX`` / ``GETDEL`` contract is pinned
    separately against a stub client in ``TestRedisBackendContract``.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.puts: list[tuple[str, str, int]] = []

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self.puts.append((key, value, ttl_seconds))
        self.store[key] = value

    async def take(self, key: str) -> str | None:
        return self.store.pop(key, None)

    def expire_all(self) -> None:
        self.store.clear()


@pytest.fixture
def credential_backend():
    """Install a fake credential store for the duration of one test."""
    backend = _FakeCredentialBackend()
    creds.set_credential_backend(backend)
    try:
        yield backend
    finally:
        creds.set_credential_backend(None)


@asynccontextmanager
async def _dispatch_harness():
    """Patch the SSRF check and the deferred task; yield the task mock.

    The SSRF check is patched because it resolves DNS, and a unit test that
    depends on ``example.com`` resolving is a test that fails on a plane. Its
    refusal path gets its own test, which patches it to raise instead.
    """
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.reupload_service_task.return_value = task
    with (
        patch.object(router_refresh, "validate_url_for_ssrf", AsyncMock()),
        patch.object(router_refresh, "get_catalog_port", return_value=port),
    ):
        yield task


async def _service_dataset(
    session,
    *,
    created_by: uuid.UUID,
    source_format: str = "wfs",
    base_url: str = _WFS_BASE,
    layer_id: str | int = "topp:parcels",
    visibility: str = "public",
):
    """A dataset bound to a service origin the way ingest binds one."""
    dataset = await _create_dataset(
        session,
        created_by=created_by,
        source_format=source_format,
        visibility=visibility,
    )
    enriched = (
        f"{base_url}/{layer_id}"
        if source_format == "arcgis_featureserver"
        else base_url
    )
    dataset.source_url = enriched
    set_dataset_origin(
        dataset,
        "service",
        uri=enriched,
        service_type=source_format,
        url=base_url,
        layer_id=str(layer_id),
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _run_for(session, dataset_id: uuid.UUID) -> DatasetRefreshRun | None:
    return (
        await session.execute(
            select(DatasetRefreshRun).where(DatasetRefreshRun.dataset_id == dataset_id)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# The pointer is server-side
# ---------------------------------------------------------------------------


class TestRequestCarriesNoPointer:
    def test_the_request_model_has_no_source_fields(self) -> None:
        """Structural, not behavioural.

        A handler that reads the binding while the model still ACCEPTS a url
        is one careless line from honouring it. The guarantee worth having is
        that there is nowhere to put one.
        """
        assert set(DatasetRefreshRequest.model_fields) == {"token"}

    def test_unknown_source_fields_are_not_silently_accepted(self) -> None:
        parsed = DatasetRefreshRequest.model_validate(
            {"url": "https://evil.example/wfs", "layer_name": "parcels"}
        )
        assert not hasattr(parsed, "url")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestRefreshDispatch:
    async def test_public_service_refreshes_with_zero_re_entry(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 202, resp.text
        payload = resp.json()
        assert payload["origin_kind"] == "service"
        assert payload["trigger"] == "api"
        assert payload["status"] == "pending"

        run = await _run_for(test_db_session, dataset.id)
        assert run is not None
        assert str(run.id) == payload["run_id"]
        assert (run.trigger, run.origin_kind, run.status) == (
            "api",
            "service",
            "pending",
        )
        assert run.triggered_by == admin_id
        assert run.feature_count_before == dataset.feature_count

        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["source_url"] == _WFS_BASE
        assert kwargs["source_layer"] == "topp:parcels"
        assert kwargs["dataset_id"] == str(dataset.id)
        assert kwargs["credential_ref"] is None

    async def test_body_is_optional(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """One request means one request: no body at all is the common case."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 202, resp.text

    async def test_wfs_binding_round_trips_through_the_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The typename addresses the layer, so it travels as the layer NAME.

        ``layer_id`` must stay None for WFS: the worker composes the enriched
        source url as ``base/layer_id`` when it is set, so a stray value here
        would append the typename to the URL and store a pointer that has
        never addressed anything.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 202

        job = (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.id == uuid.UUID(resp.json()["job_id"])
                )
            )
        ).scalar_one()
        assert job.source_url == _WFS_BASE
        assert job.source_layer == "topp:parcels"
        assert job.user_metadata["layer_id"] is None
        assert job.user_metadata["service_type"] == "WFS"
        assert job.user_metadata["reupload"] is True
        assert job.user_metadata["refresh"] is True

    async def test_arcgis_binding_round_trips_through_the_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """ArcGIS addresses by numeric id, and the name is deliberately empty.

        ``build_gdal_source`` ignores the layer name for ArcGIS entirely, so a
        name here would be a second identifier nothing reads — and the next
        reader would trust it.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            source_format="arcgis_featureserver",
            base_url=_ARCGIS_BASE,
            layer_id=7,
        )

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 202, resp.text

        job = (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.id == uuid.UUID(resp.json()["job_id"])
                )
            )
        ).scalar_one()
        assert job.source_url == _ARCGIS_BASE
        assert job.source_layer == ""
        assert job.user_metadata["layer_id"] == "7"
        assert job.user_metadata["service_type"] == "ArcGIS FeatureServer"

    async def test_every_service_label_resolves_back_to_its_stored_format(self) -> None:
        """The label table is a reverse map, and a reverse map can rot.

        ``origin_ref`` stores the canonical format while the pipeline
        dispatches on a human label by prefix. Round-tripping every entry
        means a label that stops resolving fails here rather than in a refresh
        nobody is watching.
        """
        for stored_format, label in router_refresh._SERVICE_TYPE_LABELS.items():
            assert resolve_service_type(label) == (stored_format, stored_format)

    async def test_prior_ingest_settings_are_carried_forward(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """A service whose paging key is not OBJECTID pages wrong without it.

        ``object_id_field`` is not part of the binding — the ``origin_ref``
        allowlist is the pointer and nothing else — so a refresh that ignored
        the previous job would silently produce a different result than the
        import it claims to repeat.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        test_db_session.add(
            IngestJob(
                dataset_id=dataset.id,
                source_filename="Parcels (2026)",
                source_url=_WFS_BASE,
                source_layer="topp:parcels",
                created_by=admin_id,
                status="complete",
                completed_at=datetime.now(timezone.utc),
                user_metadata={"object_id_field": "gid"},
            )
        )
        await test_db_session.commit()

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
        assert resp.status_code == 202

        job = (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.id == uuid.UUID(resp.json()["job_id"])
                )
            )
        ).scalar_one()
        assert job.user_metadata["object_id_field"] == "gid"
        assert job.source_filename == "Parcels (2026)"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefreshRefusals:
    async def test_a_vrt_dataset_is_refused_in_refresh_vocabulary(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """An originless record type answers with refresh's own words.

        The re-upload door has a record-type guard whose message says
        "reupload" and points at VRT membership editing. Borrowing it here
        would answer a refresh with advice about a different feature, so this
        endpoint lets classify_origin's None speak instead.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset.record.record_type = "vrt_dataset"
        await test_db_session.commit()

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "refresh_not_applicable"
        assert detail["origin_kind"] is None
        assert "reupload" not in detail["message"].lower()
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_upload_dataset_is_refresh_not_applicable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session, created_by=admin_id, source_format="geojson"
        )

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"
        assert resp.json()["detail"]["origin_kind"] == "upload"
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_service_dataset_without_a_binding_is_origin_unavailable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """A pre-#1218 row whose backfill could not reconstruct the pointer.

        Distinct from ``refresh_not_applicable``: this dataset HAS a remote
        origin, GeoLens just never recorded enough of it to re-address the
        layer. Telling the user to re-upload instead would be wrong advice.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session, created_by=admin_id, source_format="wfs"
        )
        dataset.origin_ref = None
        await test_db_session.commit()

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "origin_unavailable"

    async def test_binding_without_a_layer_is_origin_unavailable(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset.origin_ref = {
            "kind": "service",
            "service_type": "wfs",
            "url": _WFS_BASE,
        }
        await test_db_session.commit()

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "origin_unavailable"

    async def test_stored_url_still_goes_through_ssrf_validation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Rule 2. "Ours" is not a safety property.

        The URL was a client's when ingest stored it, and DNS moves — a host
        that resolved publicly at import can resolve to link-local today.
        """
        from app.modules.catalog.sources.security import SSRFError

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        with patch.object(
            router_refresh,
            "validate_url_for_ssrf",
            AsyncMock(side_effect=SSRFError("resolves to a private address")),
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 400
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_a_rebind_landing_at_the_reservation_never_dispatches_the_old_origin(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1277 review): the TOCTOU between the snapshot and the reservation.

        A re-upload that was already in flight finishes mid-request: it commits
        its swap, restamps `origin_ref`, and takes its own run terminal. The
        admission index then sees no active run and lets this request in — and
        the old code dispatched the binding it had read BEFORE that swap, so
        the worker would re-fetch the old origin and restamp the old binding,
        undoing a re-upload that had already succeeded.

        The rebind is committed from a second session inside a patched
        `create_pending_run`, which puts it at the exact moment the reservation
        is taken — the tightest interleaving the window allows.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        old_base = dataset.origin_ref["url"]
        new_base = "https://elsewhere.example.com/geoserver/wfs"

        real_create_pending_run = router_refresh.create_pending_run

        async def _rebind_then_reserve(*args, **kwargs):
            set_dataset_origin(
                dataset,
                "service",
                uri=new_base,
                service_type="wfs",
                url=new_base,
                layer_id="topp:moved",
            )
            await test_db_session.commit()
            return await real_create_pending_run(*args, **kwargs)

        async with _dispatch_harness() as task:
            with patch.object(
                router_refresh, "create_pending_run", _rebind_then_reserve
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "origin_changed"
        # The point of the whole fix: the stale binding never left the door.
        task.defer_async.assert_not_awaited()
        assert old_base not in str(task.defer_async.call_args)
        # And the refusal released the dataset rather than leaving a run row
        # holding the admission index against the retry that follows.
        assert await _run_for(test_db_session, dataset.id) is None
        jobs = (
            (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.dataset_id == dataset.id)
                )
            )
            .scalars()
            .all()
        )
        assert jobs == []

    async def test_a_rebind_to_an_unrefreshable_origin_releases_the_reservation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The same race, landing on a kind that cannot refresh at all.

        A concurrent FILE re-upload rebinds the dataset to an upload origin.
        The post-reservation read raises `refresh_not_applicable`, and the
        handler has to roll the reservation back on that path too — a leaked
        run row would refuse every later refresh with dataset_busy until the
        stale sweep cancelled it an hour later.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        real_create_pending_run = router_refresh.create_pending_run

        async def _rebind_then_reserve(*args, **kwargs):
            set_dataset_origin(
                dataset,
                "upload",
                uri=None,
                filename="replacement.gpkg",
                file_hash="abc123",
            )
            dataset.source_format = "gpkg"
            await test_db_session.commit()
            return await real_create_pending_run(*args, **kwargs)

        async with _dispatch_harness() as task:
            with patch.object(
                router_refresh, "create_pending_run", _rebind_then_reserve
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "refresh_not_applicable"
        task.defer_async.assert_not_awaited()
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_an_unraced_dispatch_still_carries_the_stored_binding(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The common path, asserted against the re-read rather than assumed.

        Reserving before reading the binding is only safe if the ordinary case
        still dispatches what is stored — otherwise the fix would trade a race
        for a permanent refusal.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["source_url"] == dataset.origin_ref["url"]
        assert kwargs["source_layer"] == dataset.origin_ref["layer_id"]

    async def test_second_refresh_is_refused_as_dataset_busy(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Admission runs through the same index the commit door uses.

        And the refusal leaves nothing behind: the ingest job the refused
        request wrote rolls back with it, so a busy dataset does not
        accumulate orphan pending jobs for the stale sweep to find.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            first = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )
            second = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert first.status_code == 202
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "dataset_busy"

        jobs = (
            (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.dataset_id == dataset.id)
                )
            )
            .scalars()
            .all()
        )
        assert [str(j.id) for j in jobs] == [first.json()["job_id"]]

    async def test_a_non_owner_cannot_refresh_someone_elses_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ) -> None:
        """Rule 1: this endpoint replaces the dataset's data."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=editor_auth_header
            )

        assert resp.status_code in (403, 404)
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_anonymous_callers_are_refused(
        self, client: AsyncClient, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(f"/datasets/{dataset.id}/refresh")
        assert resp.status_code in (401, 403)

    async def test_missing_dataset_is_404(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        resp = await client.post(
            f"/datasets/{uuid.uuid4()}/refresh", headers=admin_auth_header
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# The credential never becomes durable
# ---------------------------------------------------------------------------


class TestCredentialHandoff:
    async def test_a_token_reaches_the_worker_as_a_reference_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """The sentinel is the token STRING, in every persisted surface.

        Asserting that a ``token`` key is absent passes just as happily when
        the value moved to a different key, which is exactly the shape of the
        bug this endpoint exists to avoid.
        """
        secret = "tok-" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": secret},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["credential_ref"]
        assert secret not in str(kwargs)
        assert "token" not in kwargs

        job = (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.id == uuid.UUID(resp.json()["job_id"])
                )
            )
        ).scalar_one()
        assert secret not in str(job.user_metadata)
        assert job.user_metadata["service_auth_required"] is True

        run = await _run_for(test_db_session, dataset.id)
        assert secret not in str(
            (run.error_message, run.error_code, run.schema_diff, run.origin_kind)
        )

        # And the secret really is retrievable by the reference, once.
        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

    async def test_a_token_without_a_shared_store_is_refused_at_the_door(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        """REDIS_URL is unset by default, so this is the common install.

        Dispatching anyway would produce a ``credential_expired`` failure in a
        worker an hour later whose real cause is a missing setting nothing
        mentions. Public refreshes are unaffected, which the assertion below
        pins.
        """
        from app.core.config import settings

        creds.set_credential_backend(None)
        monkeypatch.setattr(settings, "redis_url", None, raising=False)

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            refused = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": "needs-a-store"},
                headers=admin_auth_header,
            )
            allowed = await client.post(
                f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
            )

        assert refused.status_code == 503
        assert refused.json()["detail"]["code"] == "credential_store_unavailable"
        assert allowed.status_code == 202
        assert task.defer_async.await_count == 1
        assert await _run_for(test_db_session, dataset.id) is not None

    async def test_a_store_that_is_down_during_stash_returns_503_not_500(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1277 review): configured-but-unreachable is not configured.

        `credential_store_available()` only reads the setting, so a live
        outage gets past the door check and surfaces at the stash. That has to
        land as the same 503 the door returns, not an unhandled 500 — and the
        request must roll back whole, leaving no reserved run to block the
        retry that follows once the store is back.
        """

        class _DownBackend:
            async def put(self, key, value, ttl_seconds):
                raise creds.CredentialStoreUnavailable("valkey is away")

            async def take(self, key):
                raise creds.CredentialStoreUnavailable("valkey is away")

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        creds.set_credential_backend(_DownBackend())
        try:
            async with _dispatch_harness() as task:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh",
                    json={"token": "never-stashed"},
                    headers=admin_auth_header,
                )
        finally:
            creds.set_credential_backend(None)

        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "credential_store_unavailable"
        task.defer_async.assert_not_awaited()
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_a_store_that_is_down_during_claim_fails_as_an_outage(
        self,
    ) -> None:
        """The whole worker sequence, not just the mapper.

        A Valkey blip used to reach the run row as `credential_expired`,
        telling the reader to re-issue a token that was never the problem.
        """
        from app.processing.ingest.tasks_reupload import (
            _resolve_service_token,
            _service_refresh_error_code,
        )

        class _DownBackend:
            async def put(self, key, value, ttl_seconds):
                raise creds.CredentialStoreUnavailable("valkey is away")

            async def take(self, key):
                raise ConnectionError("valkey is away")

        creds.set_credential_backend(_DownBackend())
        try:
            with pytest.raises(creds.CredentialStoreUnavailable) as caught:
                await _resolve_service_token(None, "a" * 24)
        finally:
            creds.set_credential_backend(None)

        assert (
            _service_refresh_error_code(caught.value) == "credential_store_unavailable"
        )

    async def test_a_credential_is_claimable_exactly_once(
        self, credential_backend
    ) -> None:
        ref = await creds.stash_service_credential("single-use")
        assert await creds.claim_service_credential(ref) == "single-use"
        with pytest.raises(creds.CredentialExpiredError):
            await creds.claim_service_credential(ref)

    async def test_an_expired_credential_reports_expiry_not_absence_of_auth(
        self, credential_backend
    ) -> None:
        ref = await creds.stash_service_credential("short-lived")
        credential_backend.expire_all()
        with pytest.raises(creds.CredentialExpiredError):
            await creds.claim_service_credential(ref)

    async def test_the_stash_sets_the_declared_ttl(self, credential_backend) -> None:
        await creds.stash_service_credential("ttl-check")
        (_key, _value, ttl) = credential_backend.puts[0]
        assert ttl == creds.CREDENTIAL_TTL_SECONDS

    def test_the_ttl_outlives_a_full_length_job_at_the_queue_head(self) -> None:
        """fix(#1277 review): the TTL is derived, and this is the derivation.

        `worker_concurrency` defaults to 1 and refreshes share the `ingest`
        queue, so a refresh can wait behind one large import with no pickup
        guarantee from Procrastinate. The supported bound on that blocking job
        is JOB_TIMEOUT_SECONDS — past it the stale sweep fails the job and the
        queue moves — so the credential has to outlive one of those plus
        slack, or `credential_expired` becomes reachable on a healthy
        instance.
        """
        from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

        assert creds.CREDENTIAL_TTL_SECONDS > JOB_TIMEOUT_SECONDS
        assert creds.CREDENTIAL_TTL_SECONDS >= 900

    def test_the_mirrored_job_timeout_has_not_drifted(self) -> None:
        """The constant is mirrored, so pin it to the authority.

        `platform/jobs/router.py` is an API edge and importing it executes
        route registration, so `credentials.py` copies the number rather than
        importing it — the same trade `ABANDONED_RUN_CUTOFF_SECONDS` makes one
        module over. A test is what keeps a copy honest: tune the timeout
        without this, and the credential window silently stops covering it.
        """
        from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

        assert creds._QUEUE_HEAD_JOB_TIMEOUT_SECONDS == JOB_TIMEOUT_SECONDS

    async def test_a_malformed_reference_never_reaches_the_store(
        self, credential_backend
    ) -> None:
        """The ref is composed into a key, so its shape is a lookup boundary."""
        for bogus in ("", "../../other", "x", "a" * 200, "has space"):
            with pytest.raises(creds.CredentialExpiredError):
                await creds.claim_service_credential(bogus)
        assert credential_backend.store == {}

    async def test_references_are_unguessable_and_distinct(
        self, credential_backend
    ) -> None:
        refs = {await creds.stash_service_credential(f"s{i}") for i in range(20)}
        assert len(refs) == 20
        assert all(len(ref) >= 22 for ref in refs)

    async def test_an_empty_credential_is_refused_rather_than_stashed(
        self, credential_backend
    ) -> None:
        with pytest.raises(ValueError):
            await creds.stash_service_credential("")
        assert credential_backend.store == {}

    async def test_discard_releases_a_credential_whose_dispatch_never_happened(
        self, credential_backend
    ) -> None:
        ref = await creds.stash_service_credential("orphan")
        await creds.discard_service_credential(ref)
        assert credential_backend.store == {}
        await creds.discard_service_credential(None)  # tolerates the no-token case


class TestRedisBackendContract:
    """The atomicity claim lives in two Redis commands, so pin the commands.

    A fake store proves the module's own bookkeeping and nothing about
    ``GETDEL``. These two tests assert the exact calls the backend issues, so
    a refactor to ``GET`` + ``DELETE`` — which reintroduces the window between
    two claimants that the whole design exists to close — fails here.
    """

    def _backend(self) -> tuple[creds.RedisCredentialBackend, MagicMock]:
        stub = MagicMock()
        stub.set = AsyncMock(return_value=True)
        stub.getdel = AsyncMock(return_value="secret")
        backend = creds.RedisCredentialBackend.__new__(creds.RedisCredentialBackend)
        backend._client = stub
        return backend, stub

    async def test_put_uses_set_with_expiry_and_no_overwrite(self) -> None:
        backend, stub = self._backend()
        await backend.put("k", "v", 900)
        stub.set.assert_awaited_once_with("k", "v", ex=900, nx=True)

    async def test_take_uses_getdel_not_get_then_delete(self) -> None:
        backend, stub = self._backend()
        assert await backend.take("k") == "secret"
        stub.getdel.assert_awaited_once_with("k")
        stub.get.assert_not_called()
        stub.delete.assert_not_called()

    async def test_a_refused_write_is_an_error_not_a_silent_overwrite(self) -> None:
        backend, stub = self._backend()
        stub.set = AsyncMock(return_value=None)
        with pytest.raises(creds.CredentialStoreUnavailable):
            await backend.put("k", "v", 900)

    async def test_a_transport_failure_on_write_is_translated(self) -> None:
        """fix(#1277 review): redis-py exceptions must not escape this class.

        Untranslated, a connection error during stash propagated out of the
        endpoint as an unhandled 500 instead of the 503 the door is written to
        return.
        """
        backend, stub = self._backend()
        stub.set = AsyncMock(side_effect=ConnectionError("valkey is away"))
        with pytest.raises(creds.CredentialStoreUnavailable):
            await backend.put("k", "v", 900)

    async def test_a_transport_failure_on_claim_is_not_reported_as_expiry(
        self,
    ) -> None:
        """The misreport codex caught: an outage blamed on a spent token.

        Only the store ANSWERING "no such key" is evidence about the
        credential. A store that cannot be reached is evidence of nothing.
        """
        backend, stub = self._backend()
        stub.getdel = AsyncMock(side_effect=TimeoutError("valkey timed out"))
        with pytest.raises(creds.CredentialStoreUnavailable):
            await backend.take("k")

    async def test_the_message_never_carries_the_key(self) -> None:
        """redis-py bakes the command — and so the key — into its error text."""
        backend, stub = self._backend()
        stub.getdel = AsyncMock(
            side_effect=ConnectionError("GETDEL geolens:refresh-cred:abc123 failed")
        )
        with pytest.raises(creds.CredentialStoreUnavailable) as caught:
            await backend.take("geolens:refresh-cred:abc123")
        assert "abc123" not in str(caught.value)


class TestWorkerCredentialClaim:
    async def test_the_worker_prefers_the_reference_over_a_durable_token(
        self, credential_backend
    ) -> None:
        from app.processing.ingest.tasks_reupload import _resolve_service_token

        ref = await creds.stash_service_credential("from-the-store")
        assert await _resolve_service_token("durable-arg", ref) == "from-the-store"

    async def test_no_reference_leaves_the_commit_door_token_alone(
        self, credential_backend
    ) -> None:
        from app.processing.ingest.tasks_reupload import _resolve_service_token

        assert await _resolve_service_token("commit-door", None) == "commit-door"
        assert await _resolve_service_token(None, None) is None

    async def test_a_spent_reference_raises_rather_than_fetching_unauthenticated(
        self, credential_backend
    ) -> None:
        """The failure that must NOT be a fall-through.

        An unauthenticated retry would reach the origin, collect a 401, and
        report a protected service as broken — sending the reader to
        investigate a service that is working fine.
        """
        from app.processing.ingest.tasks_reupload import _resolve_service_token

        ref = await creds.stash_service_credential("spent")
        await creds.claim_service_credential(ref)
        with pytest.raises(creds.CredentialExpiredError):
            await _resolve_service_token(None, ref)

    def test_each_credential_failure_gets_its_own_run_error_code(self) -> None:
        """Three failures, three places to send the reader.

        A spent credential needs a fresh token. An unreachable store is an
        operator's split-brain config — the API accepted the token because IT
        could reach the store and the worker could not. Everything else is the
        origin or the pipeline, and collapsing either credential case into it
        sends someone to investigate a service that is working fine.
        """
        from app.processing.ingest.tasks_reupload import _service_refresh_error_code

        assert (
            _service_refresh_error_code(creds.CredentialExpiredError("x"))
            == "credential_expired"
        )
        assert (
            _service_refresh_error_code(creds.CredentialStoreUnavailable("x"))
            == "credential_store_unavailable"
        )
        assert (
            _service_refresh_error_code(RuntimeError("gdal exploded"))
            == "service_refresh_failed"
        )


# ---------------------------------------------------------------------------
# The guarded contact stamp
# ---------------------------------------------------------------------------


class TestGuardedContactStamp:
    async def _failed_run(self, session, dataset):
        from app.platform.refresh.service import create_pending_run

        job = IngestJob(
            dataset_id=dataset.id,
            status="running",
            source_url=_WFS_BASE,
            created_by=dataset.record.created_by,
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        session.add(job)
        await session.commit()
        await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=dataset.record.created_by,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        await session.commit()
        return job

    async def test_a_matching_binding_dates_the_contact(
        self, client: AsyncClient, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        job = await self._failed_run(test_db_session, dataset)

        assert dataset.last_checked_at is None
        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="service_refresh_failed",
            error_message="the origin timed out",
            contacted_origin=True,
            origin_binding=(
                dataset.origin_uri,
                dataset.origin_ref,
                dataset.source_format,
            ),
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is not None

    async def test_a_rebound_dataset_is_not_dated_by_the_old_attempt(
        self, client: AsyncClient, test_db_session
    ) -> None:
        """The race the guard exists for.

        A concurrent re-upload finishes while a doomed service fetch is still
        running. An ID-only stamp would date the NEW binding's contact from
        the OLD binding's failure — and when the rebind is to an upload, that
        is a contact time nothing could ever have produced, on a kind the
        probe refuses to correct.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        job = await self._failed_run(test_db_session, dataset)
        stale_binding = (
            dataset.origin_uri,
            dataset.origin_ref,
            dataset.source_format,
        )

        set_dataset_origin(
            dataset, "upload", uri=None, filename="replacement.gpkg", file_hash="abc"
        )
        dataset.source_format = "gpkg"
        await test_db_session.commit()

        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="service_refresh_failed",
            error_message="the origin timed out",
            contacted_origin=True,
            origin_binding=stale_binding,
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is None

    async def test_key_order_in_origin_ref_is_not_a_rebind(
        self, client: AsyncClient, test_db_session
    ) -> None:
        """jsonb compares semantically; a textual guard would false-negative."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        job = await self._failed_run(test_db_session, dataset)
        reordered = dict(reversed(list((dataset.origin_ref or {}).items())))

        await record_refresh_failure(
            test_db_session,
            ingest_job_id=job.id,
            error_code="service_refresh_failed",
            error_message="the origin timed out",
            contacted_origin=True,
            origin_binding=(dataset.origin_uri, reordered, dataset.source_format),
        )
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        assert dataset.last_checked_at is not None

    async def test_an_unguarded_contact_stamp_is_not_reachable(
        self, test_db_session
    ) -> None:
        """The unguarded shape raises rather than falling back to id-only."""
        with pytest.raises(ValueError, match="origin_binding"):
            await record_refresh_failure(
                test_db_session,
                ingest_job_id=uuid.uuid4(),
                error_code="service_refresh_failed",
                error_message="boom",
                contacted_origin=True,
            )

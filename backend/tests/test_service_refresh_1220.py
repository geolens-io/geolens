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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.schemas import DatasetRefreshRequest
from app.modules.catalog.sources.origin_probe import (
    AUTH_REQUIRED,
    HEALTHY,
    INACCESSIBLE,
    MISSING,
    NOT_FOUND,
    UNAUTHORIZED,
    OriginProbeResult,
)
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
# fix(#1746 codex r2): the third service type the marker gate has to
# answer for, and the second that cannot be probed.
_OGCAPI_BASE = "https://services.example.com/ogcapi"


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
        self.renewals: list[tuple[str, int]] = []

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self.puts.append((key, value, ttl_seconds))
        self.store[key] = value

    async def take(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def renew(self, key: str, ttl_seconds: int) -> bool:
        """Models EXPIRE: moves a live key's deadline, never revives a dead one.

        That asymmetry is the property the renewal sweep depends on, so the
        fake has to reproduce it rather than just returning True.
        """
        if key not in self.store:
            return False
        self.renewals.append((key, ttl_seconds))
        return True

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
    auth_required: bool = False,
):
    """A dataset bound to a service origin the way ingest binds one.

    fix(#1277 review round 8): the enriched pointer is ``base/layer_id`` for
    EVERY service type, not just ArcGIS. The probe sets
    ``layer_id = layer["name"]`` for WFS and OGC API, and both ingest paths
    compose the stored URL as ``base/layer_id when layer_id is not None``.
    Seeding WFS with a bare base encoded the same wrong premise the handler
    did, which is why round 1 looked self-consistent.
    """
    dataset = await _create_dataset(
        session,
        created_by=created_by,
        source_format=source_format,
        visibility=visibility,
    )
    enriched = f"{base_url}/{layer_id}"
    dataset.source_url = enriched
    set_dataset_origin(
        dataset,
        "service",
        uri=enriched,
        service_type=source_format,
        url=base_url,
        layer_id=str(layer_id),
        # fix(#1746): True or None, never False — the worker writes it this
        # way at the swap and the key is simply absent for a public origin.
        auth_required=True if auth_required else None,
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


@asynccontextmanager
async def _probe_harness(*, result=None, raises=None):
    """Patch the refresh door's token-less probe; yield the mock.

    fix(#1746 codex r1): the door no longer refuses on the stored marker
    alone, it asks the origin. Tests need to state the origin's answer, and to
    assert that the probe did NOT happen on the paths that must not pay for
    one.

    fix(#1746 codex r2): only the ArcGIS path probes, so this patches the
    ArcGIS origin probe by name. A WFS or OGC API dataset that reaches the
    probe at all is the bug this harness now also catches.
    """
    probe = AsyncMock()
    if raises is not None:
        probe.side_effect = raises
    else:
        probe.return_value = result or OriginProbeResult(HEALTHY)
    with patch.object(router_refresh, "probe_arcgis_origin", probe):
        yield probe


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
        """The typename addresses the layer, and travels in BOTH slots.

        ``build_gdal_source`` reads the layer NAME for WFS and OGC API and
        ignores ``layer_id`` — but the worker composes the stored pointer as
        ``base/layer_id`` when it is set, and the IMPORT path composes it the
        same way from the same field, because the probe sets
        ``layer_id = layer["name"]`` for these services. So both slots carry
        the identity, or a refresh rewrites the pointer the import wrote.

        fix(#1277 review round 8): this asserted ``layer_id is None`` on the
        reasoning that ``base/typename`` addressed nothing. It is exactly what
        an imported WFS dataset stores.
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
        assert job.user_metadata["layer_id"] == "topp:parcels"
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


class TestAuthRequiredRefusal:
    """fix(#1746) finding 3: the door refuses what the worker cannot do.

    Before this, a credential-less refresh of an org-only service answered
    202 and then failed ~0.5s later in the worker, where the only statement
    of the real cause was a job error message nobody was watching.

    fix(#1746 codex r1): the stored marker says the last successful pull was
    MADE with a token, which is not the same claim as "the origin demands
    one" — a public service imported while the user held a token is marked
    too. So the marker is a gate.

    fix(#1746 codex r2): and the gate resolves differently per service,
    because only ArcGIS can be asked. Its probe target is the layer the
    worker actually reads. A WFS or OGC API probe would hit GetCapabilities
    or the landing page, which says nothing about whether GetFeature or
    /items is protected, so those are refused outright rather than cleared by
    evidence that is not evidence.
    """

    _CHALLENGES = [
        OriginProbeResult(INACCESSIBLE, AUTH_REQUIRED),  # ArcGIS 498/499
        OriginProbeResult(INACCESSIBLE, UNAUTHORIZED),  # a plain 401/403
    ]

    @staticmethod
    async def _marked_arcgis(session, *, created_by):
        return await _service_dataset(
            session,
            created_by=created_by,
            source_format="arcgis_featureserver",
            base_url=_ARCGIS_BASE,
            layer_id="0",
            auth_required=True,
        )

    # ---------------------------------------------------------------- #
    # ArcGIS: the probe target IS the resource the worker reads
    # ---------------------------------------------------------------- #

    @pytest.mark.parametrize(
        "challenge", _CHALLENGES, ids=["arcgis_envelope", "http_401"]
    )
    async def test_a_marked_arcgis_is_refused_when_the_layer_challenges(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        challenge,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            async with _probe_harness(result=challenge) as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "service_token_required"
        # The message names the field that fixes it, and the door that clears
        # the marker when the source really did go public.
        assert "`token` field" in detail["message"]
        assert "request-only" in detail["message"]
        assert "re-upload" in detail["message"]

        # The probe went to the LAYER, once — the same resource the worker
        # fetches, which is what makes its answer worth acting on.
        probe.assert_awaited_once()
        (target,) = probe.await_args.args
        assert target == f"{_ARCGIS_BASE}/0"

        # Refused before the reservation: no run row, nothing deferred, and
        # so nothing holding the dataset against the admission index.
        assert await _run_for(test_db_session, dataset.id) is None
        task.defer_async.assert_not_awaited()

    async def test_a_healthy_layer_lets_the_refresh_through(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The false-marker case, which is the whole reason for the probe.

        A public service imported while the user held a token carries the
        marker. Refusing on it alone would lock them out of every token-less
        refresh until they went through the re-upload dialog.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            async with _probe_harness(result=OriginProbeResult(HEALTHY)) as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        probe.assert_awaited_once()
        task.defer_async.assert_awaited_once()
        assert await _run_for(test_db_session, dataset.id) is not None

    @pytest.mark.parametrize(
        "outcome",
        [
            OriginProbeResult(INACCESSIBLE, "timeout"),
            OriginProbeResult(INACCESSIBLE, "network_error"),
            OriginProbeResult(INACCESSIBLE, "blocked_by_policy"),
            OriginProbeResult(MISSING, NOT_FOUND),
        ],
        ids=["timeout", "unreachable", "blocked", "missing"],
    )
    async def test_a_non_challenge_probe_outcome_fails_open(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, outcome
    ) -> None:
        """Only an auth challenge refuses.

        A probe is one request against a third party. Turning its bad day into
        a refusal would be a worse bug than the one this closes, and the
        worker is still there with copy that names the token field.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            async with _probe_harness(result=outcome):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        task.defer_async.assert_awaited_once()

    async def test_a_probe_that_raises_fails_open(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The guard cannot be the thing that 500s a request bound for 202."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            async with _probe_harness(raises=RuntimeError("origin exploded")):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        task.defer_async.assert_awaited_once()

    async def test_the_refusal_never_echoes_a_credential(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """A token is request-only; nothing about it is ever reflected back."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            async with _probe_harness(
                result=OriginProbeResult(INACCESSIBLE, AUTH_REQUIRED)
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh",
                    headers=admin_auth_header,
                    json={"token": None},
                )

        assert resp.status_code == 422, resp.text
        # Structural rather than "this particular secret is absent": the
        # refusal is composed from literals and reads one boolean.
        assert "auth_required" not in resp.text
        await test_db_session.refresh(dataset)
        assert "token" not in str(dataset.origin_ref)

    # ---------------------------------------------------------------- #
    # WFS and OGC API: nothing reachable can answer the question
    # ---------------------------------------------------------------- #

    @pytest.mark.parametrize(
        ("source_format", "base_url", "layer_id"),
        [
            ("wfs", _WFS_BASE, "topp:parcels"),
            ("ogcapi_features", _OGCAPI_BASE, "parcels"),
        ],
        ids=["wfs", "ogcapi_features"],
    )
    async def test_a_marked_header_auth_service_is_refused_without_probing(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        source_format: str,
        base_url: str,
        layer_id: str,
    ) -> None:
        """fix(#1746 codex r2): a probe here could only ask the wrong question.

        ``service_probe_target`` deliberately aims a WFS at GetCapabilities
        and an OGC API at its landing page, because those are the documents
        whose reachability describes the service. Neither is the resource the
        worker fetches, and a public capabilities document in front of a
        protected GetFeature is an ordinary deployment — so a healthy answer
        would be evidence of nothing while reading as permission to proceed.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            source_format=source_format,
            base_url=base_url,
            layer_id=layer_id,
            auth_required=True,
        )

        async with _dispatch_harness() as task:
            async with _probe_harness() as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "service_token_required"
        # Not asked, because nothing it could reach would answer.
        probe.assert_not_awaited()
        assert await _run_for(test_db_session, dataset.id) is None
        task.defer_async.assert_not_awaited()

    async def test_the_header_auth_refusal_names_the_way_out(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The refusal must not read as a permanent trap.

        A marked WFS that genuinely went public cannot clear itself through
        this door, so the message has to name the one that still allows a
        token-less pull.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, auth_required=True
        )

        async with _dispatch_harness():
            async with _probe_harness():
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        message = resp.json()["detail"]["message"]
        assert "re-upload" in message
        assert "without a token" in message

    # ---------------------------------------------------------------- #
    # Session handling across the probe
    # ---------------------------------------------------------------- #

    async def test_the_session_is_released_across_the_probe_and_re_read_after(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1746 codex r2): the pool must not be held across the wait.

        The probe can hold its full deadline against a slow origin, and a
        session held across it pins one of the pool's connections — enough
        concurrent marked refreshes would starve every other database-backed
        request. ``check_source_health`` already releases; so does this.

        The re-read afterwards is the other half. Rolling back expires the ORM
        instance, and the lines below the guard read it
        (``dataset.feature_count`` at the reservation, then a ``db.refresh``),
        where an async lazy load raises rather than quietly re-querying.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await self._marked_arcgis(test_db_session, created_by=admin_id)

        calls: list[str] = []
        real_get_dataset = router_refresh.get_dataset

        async def _tracking_get_dataset(db, ds_id, *args, **kwargs):
            calls.append("get_dataset")
            return await real_get_dataset(db, ds_id, *args, **kwargs)

        async def _probe(_target):
            calls.append("probe")
            return OriginProbeResult(HEALTHY)

        real_rollback = AsyncSession.rollback

        async def _tracking_rollback(self):
            calls.append("rollback")
            return await real_rollback(self)

        with (
            patch.object(router_refresh, "get_dataset", _tracking_get_dataset),
            patch.object(router_refresh, "probe_arcgis_origin", _probe),
            patch.object(AsyncSession, "rollback", _tracking_rollback),
        ):
            async with _dispatch_harness():
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        # The door's own first read, then release, then the outbound wait,
        # then the read that re-materializes what the rest of the handler
        # touches. The ORDER is the property under test; what the request does
        # after those four is not this test's business.
        assert calls[:4] == ["get_dataset", "rollback", "probe", "get_dataset"], calls

    async def test_the_header_auth_refusal_releases_nothing(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """No network, no rollback. The refusal is a pure read of the marker."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, auth_required=True
        )

        rolled_back: list[bool] = []
        real_rollback = AsyncSession.rollback

        async def _tracking_rollback(self):
            rolled_back.append(True)
            return await real_rollback(self)

        with patch.object(AsyncSession, "rollback", _tracking_rollback):
            async with _dispatch_harness():
                async with _probe_harness() as probe:
                    resp = await client.post(
                        f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                    )

        assert resp.status_code == 422, resp.text
        probe.assert_not_awaited()
        assert rolled_back == []

    # ---------------------------------------------------------------- #
    # The reservation window
    # ---------------------------------------------------------------- #

    @staticmethod
    @asynccontextmanager
    async def _marked_inside_the_reservation_window():
        """Make the post-reservation re-read see a marker the pre-check did not.

        The real race is an authenticated re-upload of the same origin
        committing its swap between the door's first read and the read after
        the reservation. Reproducing that with two racing sessions would be a
        stopwatch test; setting the committed value on the door's own re-read
        is the same observation without the flake. ``set_committed_value``
        rather than plain assignment, so the instance is not left dirty and no
        later flush can write the simulation back to the row.
        """
        real_refresh = AsyncSession.refresh
        marked = {"done": False}

        async def _refresh(self, instance, attribute_names=None, **kwargs):
            await real_refresh(self, instance, attribute_names, **kwargs)
            if marked["done"] or not attribute_names:
                return
            if "origin_ref" not in attribute_names:
                return
            marked["done"] = True
            set_committed_value(
                instance,
                "origin_ref",
                {**(instance.origin_ref or {}), "auth_required": True},
            )

        with patch.object(AsyncSession, "refresh", _refresh):
            yield

    async def test_a_marker_that_lands_during_the_reservation_is_caught(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1746 codex r3): the binding check cannot see this one.

        An authenticated re-upload commits its swap while this refresh is
        reserving. The origin did not move, so ``origin != candidate`` passes,
        and without the recheck the dispatch goes out token-less into the
        worker failure the whole guard exists to prevent.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        assert "auth_required" not in (dataset.origin_ref or {})

        async with _dispatch_harness() as task:
            async with _probe_harness() as probe:
                async with self._marked_inside_the_reservation_window():
                    resp = await client.post(
                        f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                    )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "service_token_required"
        # Unmarked at the pre-check, so the pre-reservation guard had nothing
        # to ask about and correctly did not.
        probe.assert_not_awaited()
        # The point: the token-less dispatch never left the door.
        task.defer_async.assert_not_awaited()
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

    async def test_a_marker_landing_during_the_reservation_is_fine_with_a_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """The recheck asks for a credential; it does not lock the dataset.

        Same race, same window, but this caller sent the thing the marker is
        asking for, so there is nothing to refuse.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            async with _probe_harness():
                async with self._marked_inside_the_reservation_window():
                    resp = await client.post(
                        f"/datasets/{dataset.id}/refresh",
                        headers=admin_auth_header,
                        json={"token": "tok-" + uuid.uuid4().hex},
                    )

        assert resp.status_code == 202, resp.text
        task.defer_async.assert_awaited_once()
        assert await _run_for(test_db_session, dataset.id) is not None

    # ---------------------------------------------------------------- #
    # The paths that must cost nothing at all
    # ---------------------------------------------------------------- #

    async def test_a_marked_dataset_with_a_token_still_dispatches(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """The marker is a prompt for a credential, not a lock on the dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session, created_by=admin_id, auth_required=True
        )

        async with _dispatch_harness() as task:
            async with _probe_harness() as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh",
                    headers=admin_auth_header,
                    json={"token": "tok-" + uuid.uuid4().hex},
                )

        assert resp.status_code == 202, resp.text
        # A token was sent, so there is nothing to ask the origin.
        probe.assert_not_awaited()
        task.defer_async.assert_awaited_once()
        assert await _run_for(test_db_session, dataset.id) is not None

    async def test_an_unmarked_dataset_without_a_token_still_dispatches(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """No backfill is owed: an absent key means "not known to need auth".

        Every dataset imported before the marker existed sits here, and each
        one keeps refreshing exactly the way it did.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        assert "auth_required" not in (dataset.origin_ref or {})

        async with _dispatch_harness() as task:
            async with _probe_harness() as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        # The marker is the gate: an unmarked dataset pays for no probe at
        # all, so the common refresh costs exactly what it always did.
        probe.assert_not_awaited()
        task.defer_async.assert_awaited_once()

    async def test_a_stored_false_is_not_a_reason_to_refuse(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """``is True``, not truthiness — the same rule ``managed`` reads by."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset.origin_ref = {**(dataset.origin_ref or {}), "auth_required": False}
        await test_db_session.commit()

        async with _dispatch_harness():
            async with _probe_harness() as probe:
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        assert resp.status_code == 202, resp.text
        probe.assert_not_awaited()

    @pytest.mark.parametrize(
        ("source_format", "record_type"),
        [
            (None, "vector_dataset"),  # registered postgis table
            ("stac", "vector_dataset"),
            ("geojson", "vector_dataset"),  # upload
            ("wfs", "vrt_dataset"),  # originless record type
        ],
        ids=["postgis", "stac", "upload", "vrt"],
    )
    async def test_a_non_service_origin_can_never_reach_the_refusal(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        source_format: str | None,
        record_type: str,
    ) -> None:
        """The placement claim, stated as behaviour.

        The check sits after the postgis and stac early returns and after
        ``_resolve_service_origin``, so a stray ``auth_required`` on a row of
        any other kind is inert. The allowlist would never write one there;
        the JSONB column would happily store one.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session, created_by=admin_id, source_format=source_format
        )
        dataset.record.record_type = record_type
        dataset.origin_ref = {"auth_required": True}
        await test_db_session.commit()

        async with _dispatch_harness():
            async with _probe_harness(
                result=OriginProbeResult(INACCESSIBLE, AUTH_REQUIRED)
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        body = resp.json()
        detail = body.get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code != "service_token_required", resp.text


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
        from app.platform.security import SSRFError

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

    async def test_an_unchanged_binding_still_picks_up_new_ingest_settings(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """fix(#1277 review): the binding check is not the whole check.

        A re-upload of the SAME url and the SAME layer completing during
        admission leaves `origin_ref` byte-identical, so the binding re-read
        passes and this request is admitted — correctly. But it also writes a
        new ingest job, and `object_id_field` from that job is the ArcGIS
        paging order key. Reading it before the reservation carried the
        previous key forward, paging the service by a column that may no
        longer be its identifier: features silently duplicated or dropped, on
        a refresh that reported success.

        So every piece of dispatched state is read after the reservation, not
        just the binding.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        test_db_session.add(
            IngestJob(
                dataset_id=dataset.id,
                source_filename="Parcels (old)",
                source_url=_WFS_BASE,
                source_layer="topp:parcels",
                created_by=admin_id,
                status="complete",
                completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                user_metadata={"object_id_field": "old_gid"},
            )
        )
        await test_db_session.commit()

        real_create_pending_run = router_refresh.create_pending_run

        async def _reingest_then_reserve(*args, **kwargs):
            # Same url, same layer — the binding does not move — but a newer
            # completed job now carries a different paging key.
            test_db_session.add(
                IngestJob(
                    dataset_id=dataset.id,
                    source_filename="Parcels (new)",
                    source_url=_WFS_BASE,
                    source_layer="topp:parcels",
                    created_by=admin_id,
                    status="complete",
                    completed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                    user_metadata={"object_id_field": "new_gid"},
                )
            )
            await test_db_session.commit()
            return await real_create_pending_run(*args, **kwargs)

        async with _dispatch_harness():
            with patch.object(
                router_refresh, "create_pending_run", _reingest_then_reserve
            ):
                resp = await client.post(
                    f"/datasets/{dataset.id}/refresh", headers=admin_auth_header
                )

        # Admitted, because the binding genuinely did not change.
        assert resp.status_code == 202, resp.text
        job = (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.id == uuid.UUID(resp.json()["job_id"])
                )
            )
        ).scalar_one()
        assert job.user_metadata["object_id_field"] == "new_gid"
        assert job.source_filename == "Parcels (new)"

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

    def test_the_ttl_survives_a_skipped_renewal_cycle(self) -> None:
        """fix(#1277 review round 2): the TTL is bounded by renewal now.

        Round 1 derived it from JOB_TIMEOUT_SECONDS, which turned out not to
        bound anything relevant: the heartbeat keeps a healthy long import
        alive indefinitely, so that constant bounds a DEAD worker's lease. The
        mirrored constant and its drift test went with the premise — a dead
        mirror is worse than no mirror.

        What replaces it is arithmetic against the interval renewal actually
        runs on: survive at least two cycles, so one skipped pass (a slow
        sweep, a GC pause, a restart between cycles) cannot expire a
        credential whose task is still queued.
        """
        assert (
            creds.CREDENTIAL_TTL_SECONDS > 2 * creds.CREDENTIAL_RENEWAL_INTERVAL_SECONDS
        )

    def test_the_sweeper_drives_renewal_on_the_interval_the_ttl_assumes(self) -> None:
        """The arithmetic above is only true if the loop uses this interval.

        Structural, because the alternative is waiting five minutes. The
        constant lives in the credential module precisely so there is one of
        it; this asserts the lifespan sweeper sleeps on that one rather than
        on a literal that could drift away from the TTL it justifies.
        """
        import inspect

        from app.api import main

        source = inspect.getsource(main.lifespan)
        assert "await asyncio.sleep(CREDENTIAL_RENEWAL_INTERVAL_SECONDS)" in source
        assert "renew_queued_credentials_once()" in source

    def test_the_sweeper_never_renews_outside_a_tenant_context(self) -> None:
        """fix(#1277 review round 3): the renewal is tenant-scoped now.

        It used to open its own session after ``sweep_stale_jobs_once`` had
        exited every ``tenant_job_context`` block, so in multi-tenant mode the
        query ran with no ``app.current_tenant`` — reading across tenants
        today, and returning nothing for all of them once #998 enables FORCE
        RLS on the tables it joins.

        Structural, and this is the assertion that fails against the previous
        code: the lifespan loop must reach renewal only through the
        tenant-aware helper, never by calling the raw query function itself.
        """
        import inspect

        from app.api import main

        lifespan_source = inspect.getsource(main.lifespan)
        assert "renew_queued_refresh_credentials" not in lifespan_source, (
            "the sweeper must go through renew_queued_credentials_once, which "
            "scopes the query per tenant"
        )

        helper = inspect.getsource(creds.renew_queued_credentials_once)
        assert "tenant_job_context" in helper
        assert "is_multi_tenant()" in helper
        # fix(#1277 review round 4): and the worker hosts it too. API liveness
        # does not bound an already-committed task's wait, so a single host
        # let a healthy worker find a credential the API's downtime expired.
        from app.platform.jobs import worker

        assert "renew_credentials_periodically" in inspect.getsource(worker.main)

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


# ---------------------------------------------------------------------------
# Credential renewal (#1277 review round 2)
# ---------------------------------------------------------------------------


class TestCredentialRenewal:
    """The TTL is short because renewal keeps it honest, not because the queue
    is short. Round 1 assumed a constant could bound the wait; the heartbeat
    means it cannot, so the bound is now "the dispatch is still queued".

    Three independent stops, one test each, because a renewal that keeps
    re-arming past any of them is durable storage wearing a TTL.
    """

    async def _dispatch(
        self,
        session,
        *,
        ref: str,
        pj_status: str = "todo",
        run_status: str = "pending",
        run_age_seconds: int = 0,
    ):
        from datetime import datetime, timedelta, timezone

        import sqlalchemy as sa

        from app.platform.refresh.service import create_pending_run

        admin_id = await get_user_id(session, "admin")
        dataset = await _service_dataset(session, created_by=admin_id)
        job = IngestJob(
            dataset_id=dataset.id,
            source_url=_WFS_BASE,
            source_layer="topp:parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        run = await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="api",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
        run.status = run_status
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=run_age_seconds)
        # Procrastinate's insert trigger writes procrastinate_events through
        # unqualified names, so the schema has to be on the search_path for a
        # hand-written INSERT the way it is for the library's own.
        await session.execute(sa.text("SET LOCAL search_path TO catalog, public"))
        await session.execute(
            sa.text(
                "INSERT INTO catalog.procrastinate_jobs "
                "(queue_name, task_name, args, status) "
                "VALUES ('ingest', 'reupload_service', "
                "jsonb_build_object('job_id', CAST(:job_id AS text), "
                "'credential_ref', CAST(:ref AS text)), "
                "CAST(:pj_status AS catalog.procrastinate_job_status))"
            ),
            {"job_id": str(job.id), "ref": ref, "pj_status": pj_status},
        )
        await session.commit()
        return dataset, job

    async def test_a_still_queued_dispatch_gets_its_ttl_re_armed(
        self, client, test_db_session, credential_backend
    ) -> None:
        ref = await creds.stash_service_credential("still-waiting")
        await self._dispatch(test_db_session, ref=ref)

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1
        # Still claimable afterwards — renewal must not consume it.
        assert await creds.claim_service_credential(ref) == "still-waiting"

    async def test_a_dispatch_being_worked_on_is_still_renewed(
        self, client, test_db_session, credential_backend
    ) -> None:
        """fix(#1277 review round 7): 'doing' does not mean the key is gone.

        Procrastinate flips the row to 'doing' BEFORE invoking the task, and
        the task revalidates its URL for SSRF — an unbounded DNS resolution —
        before it claims the credential. Renewal keyed on 'todo' alone
        therefore stopped during that pre-claim window, and a stalled resolver
        longer than the TTL expired the credential of a refresh that was
        actively being worked on.

        The predicate now matches the abandonment sweep's liveness test
        exactly, which is the same deferral round 5 applied to the run side.
        """
        ref = await creds.stash_service_credential("being-worked-on")
        await self._dispatch(test_db_session, ref=ref, pj_status="doing")

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1
        # Untouched by the renewal — still there for the claim to consume.
        assert await creds.claim_service_credential(ref) == "being-worked-on"

    async def test_renewal_stops_at_the_claim_rather_than_the_status_flip(
        self, client, test_db_session, credential_backend
    ) -> None:
        """What makes 'doing' safe to include: EXPIRE cannot resurrect.

        Renewal self-terminates at the real claim event instead of at a status
        flip that merely precedes it. Once GETDEL has removed the key, every
        later cycle is a no-op on a key that does not exist — so widening the
        predicate cannot keep a consumed credential alive, which is the whole
        reason this needed no new constant or coordination.
        """
        ref = await creds.stash_service_credential("claim-me")
        await self._dispatch(test_db_session, ref=ref, pj_status="doing")

        assert await creds.claim_service_credential(ref) == "claim-me"
        # The row is still 'doing' — only the claim has changed anything.
        assert await creds.renew_queued_refresh_credentials(test_db_session) == 0

    async def test_a_terminal_run_is_not_renewed(
        self, client, test_db_session, credential_backend
    ) -> None:
        """A finished run has nothing left to authenticate."""
        ref = await creds.stash_service_credential("run-is-over")
        await self._dispatch(test_db_session, ref=ref, run_status="failed")

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 0

    async def test_an_old_run_with_a_live_task_is_still_renewed(
        self, client, test_db_session, credential_backend
    ) -> None:
        """fix(#1277 review round 5): the sweep owns "abandoned", not this.

        An earlier version stopped renewing once the run passed
        ABANDONED_RUN_CUTOFF_SECONDS. That contradicted the sweep, which
        deliberately never cancels a run whose task is still live `todo`
        (#1274) — so a protected refresh queued behind a healthy long ingest
        kept its run while losing its credential, and the eventual claim
        failed `credential_expired` with the system's own definition saying
        the run was fine. Two modules disagreeing about the same run is worse
        than either answer.
        """
        from app.platform.refresh.service import ABANDONED_RUN_CUTOFF_SECONDS

        ref = await creds.stash_service_credential("queued-a-long-time")
        await self._dispatch(
            test_db_session,
            ref=ref,
            run_age_seconds=ABANDONED_RUN_CUTOFF_SECONDS + 3600,
        )

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1

    async def test_renewal_and_the_sweep_agree_on_the_same_run(
        self, client, test_db_session, credential_backend
    ) -> None:
        """One seeded state, both predicates, named as one invariant.

        The bug was not either predicate in isolation — each was defensible —
        it was that they disagreed. Pinning them together here means the next
        person to edit either one breaks a test that says why they have to
        move in step: a run the sweep considers alive keeps its credential.
        """
        from app.platform.refresh.service import (
            ABANDONED_RUN_CUTOFF_SECONDS,
            sweep_abandoned_refresh_runs,
        )

        ref = await creds.stash_service_credential("old-but-queued")
        dataset, _job = await self._dispatch(
            test_db_session,
            ref=ref,
            run_age_seconds=ABANDONED_RUN_CUTOFF_SECONDS + 3600,
        )

        assert await sweep_abandoned_refresh_runs(test_db_session) == 0, (
            "the sweep must not cancel a run whose task is still live todo"
        )
        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1, (
            "and renewal must keep the credential for exactly that run"
        )
        run = await _run_for(test_db_session, dataset.id)
        assert run is not None and run.status == "pending"

    async def test_renewal_and_the_sweep_agree_while_the_task_is_executing(
        self, client, test_db_session, credential_backend
    ) -> None:
        """fix(#1277 review round 7): the same pin, for the 'doing' half.

        The sweep's liveness test is `IN ('todo', 'doing')` in all three of
        its predicates — an executing job is not abandoned — and renewal was
        narrower than that. Pinning both statuses means narrowing either side
        back to 'todo' alone breaks a test that says why they move together.
        """
        from app.platform.refresh.service import (
            ABANDONED_RUN_CUTOFF_SECONDS,
            sweep_abandoned_refresh_runs,
        )

        ref = await creds.stash_service_credential("executing-now")
        dataset, _job = await self._dispatch(
            test_db_session,
            ref=ref,
            pj_status="doing",
            run_age_seconds=ABANDONED_RUN_CUTOFF_SECONDS + 3600,
        )

        assert await sweep_abandoned_refresh_runs(test_db_session) == 0, (
            "the sweep must not cancel a run whose task is executing"
        )
        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1, (
            "and renewal must keep that run's credential through the pre-claim window"
        )
        run = await _run_for(test_db_session, dataset.id)
        assert run is not None and run.status == "pending"

    async def test_renewal_only_touches_its_own_dispatch(
        self, client, test_db_session, credential_backend
    ) -> None:
        """One renewable and one not, in the same pass."""
        live_ref = await creds.stash_service_credential("live")
        done_ref = await creds.stash_service_credential("done")
        await self._dispatch(test_db_session, ref=live_ref)
        await self._dispatch(test_db_session, ref=done_ref, run_status="succeeded")

        assert await creds.renew_queued_refresh_credentials(test_db_session) == 1

    async def test_renewal_is_a_no_op_without_a_store(
        self, client, test_db_session, monkeypatch
    ) -> None:
        """No store, nothing to renew, and no exception on the sweep path."""
        from app.core.config import settings

        creds.set_credential_backend(None)
        monkeypatch.setattr(settings, "redis_url", None, raising=False)
        assert await creds.renew_queued_refresh_credentials(test_db_session) == 0

    async def test_expire_cannot_resurrect_a_claimed_credential(
        self, credential_backend
    ) -> None:
        """Renewal races a claim and loses, which is the required direction.

        EXPIRE only moves the deadline of a key that still exists, so a
        credential consumed between the query and the re-arm stays consumed.
        """
        ref = await creds.stash_service_credential("claim-me")
        assert await creds.claim_service_credential(ref) == "claim-me"
        assert (
            await credential_backend.renew(
                "geolens:refresh-cred:" + ref, creds.CREDENTIAL_TTL_SECONDS
            )
            is False
        )


# ---------------------------------------------------------------------------
# One token policy, both sides (#1277 review round 6)
# ---------------------------------------------------------------------------


class TestServiceTokenPolicy:
    """The door and the worker must judge a token the same way.

    They did not: the request model accepted anything printable and
    whitespace-free, while the worker pinned header-auth tokens to base64url
    with a length floor. A WFS token containing '+' therefore got a 202, burned
    its single-use credential, and failed deterministically in the background —
    the caller told everything was fine right up until nothing was.
    """

    async def test_a_wfs_token_outside_the_charset_is_refused_at_the_door(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": "abc+def/ghi=="},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "invalid_service_token"
        # Nothing dispatched, and no reservation left holding the dataset.
        task.defer_async.assert_not_awaited()
        assert await _run_for(test_db_session, dataset.id) is None

    async def test_the_refusal_describes_the_policy_and_not_the_token(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """A rejected credential must not come back in the response.

        The worker's own message names the first offending character, which is
        right for a worker-side ValueError and wrong for an API body: it would
        put a fragment of a secret into a response, a log line and a job row.
        """
        secret = "tok+" + uuid.uuid4().hex
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": secret},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422
        body = resp.text
        assert secret not in body
        assert "+" not in resp.json()["detail"]["message"]
        # ...but it does say what IS allowed.
        assert "base64url" in resp.json()["detail"]["message"]

    async def test_a_short_token_is_refused_too(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """The length floor is half the policy and was equally invisible."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

        async with _dispatch_harness():
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": "short"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 422

    async def test_arcgis_keeps_its_wider_vocabulary(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,
    ) -> None:
        """The strict policy is header-auth only, and that is deliberate.

        An ArcGIS token is a urlencoded query parameter, never a header line,
        so it carries none of the smuggling risk the charset exists to prevent.
        Applying the policy everywhere would reject valid ArcGIS tokens.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(
            test_db_session,
            created_by=admin_id,
            source_format="arcgis_featureserver",
            base_url=_ARCGIS_BASE,
            layer_id=7,
        )

        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh",
                json={"token": "AAPK/secret+value=="},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        task.defer_async.assert_awaited_once()

    def test_both_sides_consume_the_same_policy(self) -> None:
        """The invariant, named where whoever edits either side will trip.

        Structural like round 8's sweep-versus-renewal pin, and for the same
        reason: neither policy was wrong on its own, so only their agreement is
        worth asserting. The worker keeps its own enforcement — the guarantee
        is about what reaches libcurl and must not rest on a validator in
        another process — but it must enforce the SHARED definition.

        fix(#1746): widened from one door to all of them. Refresh was the only
        door consuming the policy, so import commit, re-upload commit and
        service preview each judged the same token by a weaker rule and let it
        through — the second and third of those after stashing the single-use
        credential the worker was then going to reject.
        """
        import inspect

        from app.core import service_tokens
        from app.modules.catalog.datasets.api import router_refresh, router_reupload
        from app.modules.catalog.sources import preview
        from app.processing.ingest import ogr, service

        worker_source = inspect.getsource(ogr._sanitize_authorization_token)
        assert "HEADER_TOKEN_CHARSET" in worker_source
        assert "HEADER_TOKEN_MIN_LENGTH" in worker_source
        # No private copy of the charset survives anywhere in the module.
        assert "_BASE64URL_CHARSET" not in inspect.getsource(ogr)

        # Every door that can hand a service token to the worker, by the name
        # whoever adds the next one will search for. The import door's check is
        # a named helper (inline pushed `queue_ingest_job` past ruff's C901
        # ceiling), so the call site is asserted alongside it.
        for door in (
            router_refresh.refresh_dataset,
            router_reupload.reupload_commit,
            service._assert_header_token_dispatchable,
        ):
            door_source = inspect.getsource(door)
            assert "header_token_rejection_reason" in door_source, door.__name__
            assert "requires_header_token_policy" in door_source, door.__name__
        assert "_assert_header_token_dispatchable" in inspect.getsource(
            service.queue_ingest_job
        )

        # Preview is the fourth consumer and selects the header-auth case
        # differently: it holds a composed GDAL source string, not a stored
        # `source_format`, so the `WFS:`/`OAPIF:` prefix IS the selector and
        # `requires_header_token_policy` has nothing to answer for it. It must
        # still judge the token by the shared rule — it used to accept anything
        # printable, so a token that could never import previewed cleanly.
        preview_source = inspect.getsource(preview.run_service_preview)
        assert "header_token_rejection_reason" in preview_source

        # And the policy text itself never interpolates the token. The
        # worker's message DOES name the offending character, deliberately —
        # a worker ValueError is read by whoever debugs a failed job, while an
        # HTTP body must never echo part of a submitted credential.
        assert "{" not in service_tokens.HEADER_TOKEN_POLICY


class TestRefreshDoesNotRespellTheBinding:
    """fix(#1277 review round 8): a refresh re-ingests; it must not rewrite
    how the origin is spelled.

    The worker composes the stored pointer as ``base/layer_id`` when layer_id
    is set, and the import path does the same from the same field — the probe
    sets ``layer_id = layer["name"]`` for WFS and OGC API. A refresh that
    passed None therefore migrated a dataset from ``base/typename`` to bare
    ``base``, changing the spelling of a binding it had just verified
    unchanged.

    origin_ref never showed it, because that round-trips through
    ``service_layer_identity``. The pointer degraded underneath a green test.
    """

    async def test_the_dispatch_composes_the_pointer_the_import_wrote(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """Both paths build it from layer_id, so both must receive one.

        Asserted against the import's own composition rather than a literal,
        so the two cannot drift apart without this failing.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)

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
        layer_id = job.user_metadata["layer_id"]
        # tasks_vector.ingest_service and tasks_reupload.reupload_service share
        # this expression verbatim; this is it.
        composed = (
            f"{job.source_url}/{layer_id}" if layer_id is not None else job.source_url
        )
        assert composed == dataset.origin_uri
        assert composed == dataset.source_url

    async def test_the_post_refresh_pointer_still_matches_the_duplicate_guard(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The reported symptom, at the value the guard actually compares.

        The duplicate-source guard matches ``Dataset.origin_uri`` against the
        enriched URL a fresh preview rebuilds. A refresh that respelled the
        pointer to the bare base therefore stopped matching, and a second
        import of the same layer was allowed through as a new dataset.

        Driving the real swap needs a live WFS service, so this asserts the
        value the worker WOULD write — the shared composition — against the
        value the guard looks for.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        guard_key = dataset.origin_uri

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

        layer_id = job.user_metadata["layer_id"]
        rewritten = (
            f"{job.source_url}/{layer_id}" if layer_id is not None else job.source_url
        )
        assert rewritten == guard_key, (
            "a refresh must leave origin_uri byte-identical, or the duplicate "
            "guard stops recognising the dataset it already has"
        )

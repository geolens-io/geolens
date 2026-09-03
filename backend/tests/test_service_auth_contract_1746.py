"""feat(#1746): the structured ``auth`` request contract at the service doors.

Every door that can be handed a credential for a remote service accepts a
nested ``auth`` object saying HOW to present it, alongside the flat ``token``
field that has always meant a bearer credential. The doors are probe, service
preview, re-upload service preview, re-upload commit and refresh.

Four properties, asserted per door because each can regress on its own:

- an ``auth`` object with method ``bearer`` reaches the layer underneath
  exactly as the flat ``token`` does, so the two spellings cannot drift;
- a body that sets both is refused, rather than one winning by an ordering
  nobody wrote down;
- an ``auth`` object whose fields do not match its method is refused, and the
  refusal names the rule and never the value the caller typed;
- a method the named service cannot carry is refused with 422
  ``unsupported_auth_method``. Since the transport lane that is
  ``build_credential_header``\'s two consumers, that means an ArcGIS origin
  and a username and password or a named API key: an ArcGIS credential is
  percent-encoded into the request URL, which has room for a token and nothing
  else. WFS and OGC API Features send a header and take all three methods.
  A closed door rather than a request that is accepted and then fetched
  unauthenticated, which fails at the origin with a 401 and reads like a
  credential problem rather than a missing feature.

The last class is the D2 constraint from the plan: the refresh dispatch
decision and the ingest queue both take a ``ServiceCredential`` as a parameter
in their own right, so a caller with no HTTP layer can pass one. Those tests
call the functions directly and never build a request.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources.schemas import (
    SERVICE_AUTH_BASIC_POLICY,
    SERVICE_AUTH_BEARER_POLICY,
    SERVICE_AUTH_CONFLICT_POLICY,
    SERVICE_AUTH_HEADER_POLICY,
    ProbeResponse,
)
from app.platform import security
from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.service_auth import (
    BLANK_BEARER_TOKEN_CODE,
    BLANK_BEARER_TOKEN_POLICY,
    UNSUPPORTED_AUTH_METHOD_CODE,
    UNSUPPORTED_AUTH_METHOD_POLICY,
    bearer_token_for_credential,
)
from tests.factories import create_dataset, get_user_id
from tests.test_import_token_lease_1676 import (  # noqa: F401
    _reupload_harness,
    no_credential_store,
)
from tests.test_service_refresh_1220 import (  # noqa: F401
    _dispatch_harness,
    _service_dataset,
    credential_backend,
)

pytestmark = pytest.mark.anyio

_WFS_URL = "https://services.example.test/geoserver/wfs"
# An ArcGIS-shaped URL, which is what every door uses to select the
# URL-query transport that cannot carry a basic or header-key credential.
_ARCGIS_URL = "https://services.example.test/rest/services/Parcels/FeatureServer"


def _bearer_secret() -> str:
    """A token the header-auth policy accepts, unique per call.

    Unique so an assertion that it is absent from a response body cannot pass
    by coincidence, and inside the base64url alphabet so the WFS doors judge it
    on the ``auth`` contract rather than refusing it on charset.
    """
    return "tok" + uuid.uuid4().hex


def _opaque_value() -> str:
    """A credential value with no literal spelled anywhere in this file."""
    return uuid.uuid4().hex


def _basic_auth() -> tuple[dict, list[str]]:
    """A well-formed basic ``auth`` object and the values it must not echo."""
    username = _opaque_value()
    password = _opaque_value()
    return (
        {"method": "basic", "username": username, "password": password},
        [username, password],
    )


def _header_auth() -> tuple[dict, list[str]]:
    value = _opaque_value()
    return (
        {"method": "header", "header_name": "X-Api-Key", "header_value": value},
        [value],
    )


def _assert_unsupported_without_the_values(resp, secrets: list[str]) -> None:
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == UNSUPPORTED_AUTH_METHOD_CODE
    assert detail["message"] == UNSUPPORTED_AUTH_METHOD_POLICY
    for secret in secrets:
        assert secret not in resp.text


def _assert_shape_refusal_without_the_values(resp, secrets: list[str]) -> None:
    """A pydantic 422, carrying the rule and none of the fields it judged."""
    assert resp.status_code == 422, resp.text
    for secret in secrets:
        assert secret not in resp.text


async def _wfs_reupload_job(
    session,
    *,
    dataset_id: uuid.UUID,
    created_by: uuid.UUID,
    service_type: str = "WFS 2.0.0",
    source_url: str = _WFS_URL,
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Parcels",
        source_url=source_url,
        source_layer="topp:parcels",
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": service_type,
            "layer_id": 0 if service_type.startswith("ArcGIS") else None,
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Door 1: probe (POST /services/probe)
# ---------------------------------------------------------------------------


class TestProbeDoor:
    async def _post(
        self, client: AsyncClient, headers: dict, body: dict, url: str = _WFS_URL
    ):
        probe = AsyncMock(
            return_value=ProbeResponse(
                service_type="WFS 2.0.0", url=_WFS_URL, layers=[]
            )
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", probe),
        ):
            resp = await client.post(
                "/services/probe", json={"url": url, **body}, headers=headers
            )
        return resp, probe

    async def test_auth_bearer_reaches_the_probe_as_the_flat_token_does(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        secret = _bearer_secret()

        flat_resp, flat_probe = await self._post(
            client, admin_auth_header, {"token": secret}
        )
        auth_resp, auth_probe = await self._post(
            client, admin_auth_header, {"auth": {"method": "bearer", "token": secret}}
        )

        assert flat_resp.status_code == 200, flat_resp.text
        assert auth_resp.status_code == 200, auth_resp.text
        assert auth_probe.await_args.kwargs["credential"].token == secret
        assert auth_probe.await_args.kwargs == flat_probe.await_args.kwargs

    async def test_both_spellings_at_once_are_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        secret = _bearer_secret()
        resp, probe = await self._post(
            client,
            admin_auth_header,
            {"token": secret, "auth": {"method": "bearer", "token": secret}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_CONFLICT_POLICY in resp.text
        probe.assert_not_awaited()

    async def test_fields_that_do_not_match_the_method_are_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        username = _opaque_value()
        resp, probe = await self._post(
            client,
            admin_auth_header,
            {"auth": {"method": "basic", "username": username}},
        )
        _assert_shape_refusal_without_the_values(resp, [username])
        assert SERVICE_AUTH_BASIC_POLICY in resp.text
        probe.assert_not_awaited()

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_method_with_no_transport_reaches_detection(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        """fix(#1746 B2b review r27): the refusal moved AFTER detection.

        This asserted the opposite: that an ArcGIS-SHAPED URL was refused
        before the network. That was the finding. `_looks_like_arcgis` matches
        `FeatureServer` or `MapServer` anywhere in a URL, so a WFS served from
        `/FeatureServer/wfs` was refused a credential it supports, before
        anything had asked the service what it is — and asking is the whole
        point of a probe.

        The credential's SHAPE is still judged at the door, because that is
        answerable without asking anyone. Whether the service found can carry
        the method is answered by `service_carries_method` once there is a
        service to ask about, which is what the sibling test below pins.
        """
        auth, secrets = builder()
        resp, probe = await self._post(
            client, admin_auth_header, {"auth": auth}, url=_ARCGIS_URL
        )

        assert resp.status_code == 200, resp.text
        # The whole credential reached detection, which is now what decides.
        assert probe.await_args.kwargs["credential"].method == auth["method"]
        for secret in secrets:
            assert secret not in resp.text

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_wfs_behind_an_arcgis_shaped_path_is_probed(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        """The case the URL-text refusal broke, stated directly.

        `/FeatureServer/wfs` is a WFS. It supports basic and a named API key,
        and the door has no business deciding otherwise from the path.
        """
        auth, secrets = builder()
        resp, probe = await self._post(
            client,
            admin_auth_header,
            {"auth": auth},
            url="https://service.example/geoserver/FeatureServer/wfs",
        )

        assert resp.status_code == 200, resp.text
        assert probe.await_args.kwargs["credential"].method == auth["method"]
        for secret in secrets:
            assert secret not in resp.text

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_an_arcgis_service_still_refuses_the_method(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        """Same code as before, decided by what was found rather than the URL.

        Driven through the real `detect_service_type`, since the refusal now
        lives there: a mocked detector would prove only that the door stopped
        refusing.
        """
        auth, secrets = builder()
        recorded: list[httpx.Request] = []

        def _handle(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            # An ArcGIS FeatureServer answering as one.
            return httpx.Response(
                200,
                json={
                    "currentVersion": 11.1,
                    "layers": [{"id": 0, "name": "Parcels", "type": "Feature Layer"}],
                },
            )

        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch.object(
                security, "make_safe_transport", lambda: httpx.MockTransport(_handle)
            ),
            patch.object(security, "validate_url_for_ssrf", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/services/probe",
                json={"url": _ARCGIS_URL, "auth": auth},
                headers=admin_auth_header,
            )

        _assert_unsupported_without_the_values(resp, secrets)
        # It reached the service to find out what it was, and the credential
        # was never presented in the query, since it does not fit one.
        assert recorded
        for request in recorded:
            for secret in secrets:
                assert secret not in str(request.url)

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_header_auth_service_takes_every_method(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        """feat(#1746 B2b): the 422 above is lifted where a header can be sent.

        The whole credential reaches the adapters, which compose the header
        themselves; the door hands down no bare token for a method that has
        none.
        """
        auth, secrets = builder()
        resp, probe = await self._post(client, admin_auth_header, {"auth": auth})
        assert resp.status_code == 200, resp.text
        credential = probe.await_args.kwargs["credential"]
        assert credential.method == auth["method"]
        for secret in secrets:
            assert secret not in resp.text


# ---------------------------------------------------------------------------
# Door 2: service preview (POST /services/preview)
# ---------------------------------------------------------------------------


class TestPreviewDoor:
    async def _post(
        self,
        client: AsyncClient,
        headers: dict,
        body: dict,
        service_type: str = "WFS 2.0.0",
        url: str = _WFS_URL,
    ):
        preview = AsyncMock(
            return_value={
                "srid": 4326,
                "geometry_type": "Polygon",
                "layer_name": "topp:parcels",
                "feature_count": 1,
                "columns": [],
                "sample_rows": [],
            }
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.run_service_preview", preview),
        ):
            resp = await client.post(
                "/services/preview",
                json={
                    "url": url,
                    "service_type": service_type,
                    "layer_name": "topp:parcels",
                    **body,
                },
                headers=headers,
            )
        return resp, preview

    async def test_auth_bearer_reaches_ogrinfo_as_the_flat_token_does(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        secret = _bearer_secret()

        flat_resp, flat_preview = await self._post(
            client, admin_auth_header, {"token": secret}
        )
        auth_resp, auth_preview = await self._post(
            client, admin_auth_header, {"auth": {"method": "bearer", "token": secret}}
        )

        assert flat_resp.status_code == 200, flat_resp.text
        assert auth_resp.status_code == 200, auth_resp.text
        assert auth_preview.await_args.kwargs["credential"].token == secret
        assert auth_preview.await_args.kwargs == flat_preview.await_args.kwargs

    async def test_both_spellings_at_once_are_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        secret = _bearer_secret()
        resp, preview = await self._post(
            client,
            admin_auth_header,
            {"token": secret, "auth": {"method": "bearer", "token": secret}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_CONFLICT_POLICY in resp.text
        preview.assert_not_awaited()

    async def test_fields_that_do_not_match_the_method_are_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        value = _opaque_value()
        resp, preview = await self._post(
            client,
            admin_auth_header,
            {"auth": {"method": "header", "header_value": value}},
        )
        _assert_shape_refusal_without_the_values(resp, [value])
        preview.assert_not_awaited()

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_method_with_no_transport_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        auth, secrets = builder()
        resp, preview = await self._post(
            client,
            admin_auth_header,
            {"auth": auth, "layer_id": 0},
            service_type="ArcGIS FeatureServer",
            url=_ARCGIS_URL,
        )
        _assert_unsupported_without_the_values(resp, secrets)
        preview.assert_not_awaited()

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_header_auth_service_takes_every_method(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        """feat(#1746 B2b): ogrinfo gets the credential, and no response echoes it."""
        auth, secrets = builder()
        resp, preview = await self._post(client, admin_auth_header, {"auth": auth})
        assert resp.status_code == 200, resp.text
        credential = preview.await_args.kwargs["credential"]
        assert credential.method == auth["method"]
        assert credential.service_format == "wfs"
        for secret in secrets:
            assert secret not in resp.text


# ---------------------------------------------------------------------------
# Door 3: re-upload commit (POST /datasets/{id}/reupload/{job_id}/commit)
# ---------------------------------------------------------------------------


class TestReuploadCommitDoor:
    async def _dataset(self, session, *, created_by: uuid.UUID):
        return await create_dataset(
            session,
            created_by=created_by,
            name=f"Reupload {uuid.uuid4().hex[:8]}",
            visibility="public",
            feature_count=100,
            source_filename="original.geojson",
            source_url=_WFS_URL,
        )

    async def _post(
        self, client, session, headers, body: dict, service_type: str = "WFS 2.0.0"
    ):
        admin_id = await get_user_id(session, "admin")
        dataset = await self._dataset(session, created_by=admin_id)
        job = await _wfs_reupload_job(
            session,
            dataset_id=dataset.id,
            created_by=admin_id,
            service_type=service_type,
            source_url=(_ARCGIS_URL if service_type.startswith("ArcGIS") else _WFS_URL),
        )
        async with _reupload_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json=body,
                headers=headers,
            )
        return resp, task, job

    async def test_auth_bearer_is_staged_as_the_flat_token_is(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _bearer_secret()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "bearer", "token": secret}},
        )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        # The reference travels and the secret does not, which is what the flat
        # token already did. Claiming it back is what proves the auth object's
        # token, and not some other value, is what was staged.
        assert kwargs["token"] is None
        assert secret not in str(kwargs)
        # feat(#1746 B2b) plan D9: what is staged is the finished header line,
        # for a bearer credential exactly as for the other two methods, so one
        # wire format reaches the worker and one composer produced it.
        assert (
            await creds.claim_service_credential(kwargs["credential_ref"])
            == f"Authorization: Bearer {secret}"
        )

    async def test_both_spellings_at_once_are_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        secret = _bearer_secret()
        resp, task, job = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"token": secret, "auth": {"method": "bearer", "token": secret}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_CONFLICT_POLICY in resp.text
        task.defer_async.assert_not_awaited()

    async def test_fields_that_do_not_match_the_method_are_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        password = _opaque_value()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "basic", "password": password}},
        )
        _assert_shape_refusal_without_the_values(resp, [password])
        task.defer_async.assert_not_awaited()

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_method_with_no_transport_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, builder
    ) -> None:
        auth, secrets = builder()
        resp, task, job = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": auth},
            service_type="ArcGIS FeatureServer",
        )
        _assert_unsupported_without_the_values(resp, secrets)
        task.defer_async.assert_not_awaited()

        # And nothing of the credential reached the durable row this door
        # merges its request body into. `user_metadata` is JSONB, and the
        # model_dump that fills it is a whitelist by omission.
        from sqlalchemy import select

        reloaded = (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.id == job.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        for secret in secrets:
            assert secret not in str(reloaded.user_metadata)

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_header_auth_service_stages_the_composed_line(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        builder,
    ) -> None:
        """feat(#1746 B2b) plan D9: one finished header line crosses the queue.

        The value under the `token` kwarg is what the purge, the sweep and the
        log scrubber all key on, so it stays a string under that name for a
        basic credential exactly as it was for a bearer one.
        """
        auth, secrets = builder()
        resp, task, _ = await self._post(
            client, test_db_session, admin_auth_header, {"auth": auth}
        )
        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert kwargs["token"] is None
        for secret in secrets:
            assert secret not in str(kwargs)
        staged = await creds.claim_service_credential(kwargs["credential_ref"])
        assert staged.count(": ") == 1
        assert staged.startswith(
            "Authorization: Basic " if "username" in auth else "X-Api-Key: "
        )


# ---------------------------------------------------------------------------
# Door 4: refresh (POST /datasets/{id}/refresh)
# ---------------------------------------------------------------------------


class TestRefreshDoor:
    async def _post(
        self, client, session, headers, body: dict, source_format: str = "wfs"
    ):
        admin_id = await get_user_id(session, "admin")
        dataset = await _service_dataset(
            session,
            created_by=admin_id,
            source_format=source_format,
            **(
                {"base_url": _ARCGIS_URL, "layer_id": 0}
                if source_format == "arcgis_featureserver"
                else {}
            ),
        )
        async with _dispatch_harness() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/refresh", json=body, headers=headers
            )
        return resp, task, dataset

    async def test_auth_bearer_is_staged_as_the_flat_token_is(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _bearer_secret()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "bearer", "token": secret}},
        )

        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        assert secret not in str(kwargs)
        assert (
            await creds.claim_service_credential(kwargs["credential_ref"])
            == f"Authorization: Bearer {secret}"
        )

    async def test_both_spellings_at_once_are_refused(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _bearer_secret()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"token": secret, "auth": {"method": "bearer", "token": secret}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_CONFLICT_POLICY in resp.text
        task.defer_async.assert_not_awaited()

    async def test_fields_that_do_not_match_the_method_are_refused(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        username = _opaque_value()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "bearer", "username": username}},
        )
        _assert_shape_refusal_without_the_values(resp, [username])
        task.defer_async.assert_not_awaited()

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_method_with_no_transport_is_refused(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        builder,
    ) -> None:
        auth, secrets = builder()
        resp, task, dataset = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": auth},
            source_format="arcgis_featureserver",
        )
        _assert_unsupported_without_the_values(resp, secrets)
        task.defer_async.assert_not_awaited()

        # The refusal lands before the run row is reserved, so an unsupported
        # method cannot hold the dataset against the one-active-run index.
        from sqlalchemy import select

        from app.platform.refresh.models import DatasetRefreshRun

        run = (
            await test_db_session.execute(
                select(DatasetRefreshRun).where(
                    DatasetRefreshRun.dataset_id == dataset.id
                )
            )
        ).scalar_one_or_none()
        assert run is None

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_header_auth_origin_stages_the_composed_line(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        credential_backend,  # noqa: F811
        builder,
    ) -> None:
        """feat(#1746 B2b): the fourth door, and the one that judges twice.

        The credential is composed once against the dataset's own format, and
        again against the binding read back after the reservation, because an
        unchanged binding is not the same fact as an unchanged origin.
        """
        auth, secrets = builder()
        resp, task, _ = await self._post(
            client, test_db_session, admin_auth_header, {"auth": auth}
        )
        assert resp.status_code == 202, resp.text
        kwargs = task.defer_async.call_args.kwargs
        for secret in secrets:
            assert secret not in str(kwargs)
        staged = await creds.claim_service_credential(kwargs["credential_ref"])
        assert staged.count(": ") == 1
        assert staged.startswith(
            "Authorization: Basic " if "username" in auth else "X-Api-Key: "
        )


# ---------------------------------------------------------------------------
# D2: the service layer takes a credential, with no HTTP layer anywhere
# ---------------------------------------------------------------------------


class TestServiceLayerTakesACredentialDirectly:
    """Plan D2: the one thing this phase owes a caller that is not a request.

    An overlay scheduler resolves a stored credential and then wants core to
    run with it. It can only do that if there is a function that TAKES one, so
    these tests call the refresh dispatch decision and the ingest queue
    directly, with a ``ServiceCredential`` and no request, no client and no
    router.
    """

    async def test_the_refresh_dispatch_service_takes_a_credential(
        self,
        credential_backend,  # noqa: F811
    ) -> None:
        secret = _bearer_secret()
        credential = ServiceCredential(
            method=CredentialMethod.BEARER, service_format="wfs", token=secret
        )

        token, ref = await creds.resolve_dispatch_credential(
            door="overlay", credential=credential
        )

        assert token is None
        assert ref
        assert (
            await creds.claim_service_credential(ref)
            == f"Authorization: Bearer {secret}"
        )

    async def test_the_refresh_dispatch_service_stages_a_composed_line(
        self,
        credential_backend,  # noqa: F811
    ) -> None:
        """feat(#1746 B2b): the in-process caller reaches the same wire format.

        `service_format` is on the credential the caller constructs, which is
        what selects the transport when there is no request to read it from.
        """
        password = _opaque_value()
        credential = ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="wfs",
            username=_opaque_value(),
            password=password,
        )

        token, ref = await creds.resolve_dispatch_credential(
            door="overlay", credential=credential
        )

        assert token is None
        staged = await creds.claim_service_credential(ref)
        assert staged.startswith("Authorization: Basic ")
        assert password not in staged

    async def test_the_refresh_dispatch_service_refuses_a_method_with_no_transport(
        self,
        credential_backend,  # noqa: F811
    ) -> None:
        from fastapi import HTTPException

        password = _opaque_value()
        credential = ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="arcgis_featureserver",
            username=_opaque_value(),
            password=password,
        )

        with pytest.raises(HTTPException) as excinfo:
            await creds.resolve_dispatch_credential(
                door="overlay", credential=credential
            )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == UNSUPPORTED_AUTH_METHOD_CODE
        assert password not in str(excinfo.value.detail)

    async def test_the_ingest_service_takes_a_credential(
        self,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        from app.processing.ingest.service import queue_ingest_job

        secret = _bearer_secret()
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url=_WFS_URL,
            source_layer="topp:parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "WFS 2.0.0", "layer_id": None},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        task = AsyncMock()
        with patch("app.processing.ingest.tasks.ingest_service") as ingest_service:
            ingest_service.defer_async = task
            await queue_ingest_job(
                job,
                str(admin_id),
                db=test_db_session,
                credential=ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format="wfs",
                    token=secret,
                ),
            )

        kwargs = task.await_args.kwargs
        assert kwargs["token"] is None
        assert secret not in str(kwargs)
        # feat(#1746 B2b) plan D9: what is staged is the finished header line,
        # for a bearer credential exactly as for the other two methods, so one
        # wire format reaches the worker and one composer produced it.
        assert (
            await creds.claim_service_credential(kwargs["credential_ref"])
            == f"Authorization: Bearer {secret}"
        )

    async def test_the_ingest_service_refuses_a_method_with_no_transport(
        self,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        from fastapi import HTTPException

        from app.processing.ingest.service import queue_ingest_job

        value = _opaque_value()
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url=_ARCGIS_URL,
            source_layer="topp:parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "ArcGIS FeatureServer", "layer_id": 0},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        with pytest.raises(HTTPException) as excinfo:
            await queue_ingest_job(
                job,
                str(admin_id),
                db=test_db_session,
                credential=ServiceCredential(
                    method=CredentialMethod.HEADER_KEY,
                    service_format="arcgis_featureserver",
                    header_name="X-Api-Key",
                    header_value=value,
                ),
            )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == UNSUPPORTED_AUTH_METHOD_CODE
        assert value not in str(excinfo.value.detail)

    async def test_a_stale_legacy_token_does_not_refuse_a_valid_credential(
        self,
        test_db_session,
        credential_backend,  # noqa: F811
    ) -> None:
        """fix(#1746 B2b review r1): the winner is judged, not the loser.

        The signature promises `credential` wins over `token` when both are
        given, but the legacy pre-check ran first and judged `token`, so an
        overlay holding a stale bearer string alongside a fresh structured
        credential was refused for a value it had already replaced.
        """
        from app.processing.ingest.service import queue_ingest_job

        secret = _bearer_secret()
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url=_WFS_URL,
            source_layer="topp:parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "WFS 2.0.0", "layer_id": None},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        task = AsyncMock()
        with patch("app.processing.ingest.tasks.ingest_service") as ingest_service:
            ingest_service.defer_async = task
            await queue_ingest_job(
                job,
                str(admin_id),
                db=test_db_session,
                # Outside the header-token charset, so the legacy pre-check
                # refuses it on sight.
                token="stale+token/" + _opaque_value(),
                credential=ServiceCredential(
                    method=CredentialMethod.BEARER,
                    service_format="wfs",
                    token=secret,
                ),
            )

        kwargs = task.await_args.kwargs
        assert kwargs["token"] is None
        assert (
            await creds.claim_service_credential(kwargs["credential_ref"])
            == f"Authorization: Bearer {secret}"
        )

    def test_the_gate_answers_none_for_a_credential_free_call(self) -> None:
        """The absence of a credential is not an unsupported method."""
        assert bearer_token_for_credential(None) is None
        assert bearer_token_for_credential(ServiceCredential()) is None

    def test_the_policy_message_cannot_grow_an_interpolation(self) -> None:
        """Mirrors the pin on HEADER_TOKEN_POLICY in test_service_refresh_1220.

        The message reaches a 422 body and a log line, so a brace in it is the
        first half of echoing the value it was written not to name.
        """
        assert "{" not in UNSUPPORTED_AUTH_METHOD_POLICY


# ---------------------------------------------------------------------------
# Field order, which is a wire contract in the generated SDK
# ---------------------------------------------------------------------------


class TestAuthIsDeclaredLast:
    """fix(#1760 codex r2): appending is the only safe place to add this field.

    `openapi-python-client` gives every model field a positional slot in
    declaration order, so an optional field inserted ahead of an existing one
    moves that one's slot. The first version of this change put `auth` between
    `token` and `object_id_field` on `ServicePreviewRequest`, and a caller
    already writing `ServicePreviewRequest(url, type, layer, title, id, token,
    oid)` would then have sent its object-id string as `auth` and collected a
    422 naming a method it never chose. Appending cannot move a slot that
    already exists.

    Stated for all five models rather than only the one that broke, because
    the same insertion is available in each and nothing else notices it.
    """

    def test_every_model_declares_auth_last(self) -> None:
        from app.modules.catalog.datasets.domain.schemas import (
            DatasetRefreshRequest,
            ReuploadCommitRequest,
            ReuploadServicePreviewRequest,
        )
        from app.modules.catalog.sources.schemas import (
            ProbeRequest,
            ServicePreviewRequest,
        )

        for model in (
            ProbeRequest,
            ServicePreviewRequest,
            ReuploadCommitRequest,
            ReuploadServicePreviewRequest,
            DatasetRefreshRequest,
        ):
            assert list(model.model_fields)[-1] == "auth", (
                f"{model.__name__} must declare `auth` last: anywhere else "
                "shifts the positional slot of every field after it in the "
                "generated SDK constructor."
            )

    def test_the_generated_sdk_keeps_the_older_field_ahead_of_auth(self) -> None:
        """The regression itself, read off the emitted client.

        A rule about declaration order that never looks at what the generator
        produced would keep passing if the generator changed how it orders
        arguments, which is the thing the rule is really about.
        """
        from pathlib import Path

        emitted = (
            Path(__file__).resolve().parents[2]
            / "sdks"
            / "python"
            / "geolens"
            / "models"
            / "service_preview_request.py"
        ).read_text()
        assert "object_id_field:" in emitted and "auth:" in emitted
        assert emitted.index("object_id_field:") < emitted.index("auth:"), (
            "The generated SDK declares `auth` before `object_id_field`, which "
            "moves an argument callers are already passing positionally."
        )


# ---------------------------------------------------------------------------
# A blank field is not a credential
# ---------------------------------------------------------------------------


class TestABlankValueIsNotACredential:
    """fix(#1760 codex r1): the failure mode is an anonymous request, not an error.

    Every check downstream of the door is a truthiness test, so a field that
    passed the shape validator while holding `""` produced `""` at the gate and
    then no credential at all on the wire. The caller had named a method, which
    makes an anonymous fetch the one outcome they did not ask for: it reaches
    the origin, collects a 401, and reports a protected service as broken.

    Whitespace counts as blank for the same reason. None of these values may
    contain whitespace anywhere, so a blank-looking one is a typo rather than a
    credential.
    """

    async def _probe(self, client: AsyncClient, headers: dict, body: dict):
        probe = AsyncMock(
            return_value=ProbeResponse(
                service_type="WFS 2.0.0", url=_WFS_URL, layers=[]
            )
        )
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch("app.modules.catalog.sources.router.detect_service_type", probe),
        ):
            resp = await client.post(
                "/services/probe", json={"url": _WFS_URL, **body}, headers=headers
            )
        return resp, probe

    async def test_an_empty_bearer_token_is_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """The reported case.

        The message matters as much as the status: it has to be the bearer
        SHAPE refusal, which is what says the field was left blank. Asserting
        only 422 would keep passing on the old rule, because the value still
        reaches the gate and gets refused there for a different reason.
        """
        resp, probe = await self._probe(
            client, admin_auth_header, {"auth": {"method": "bearer", "token": ""}}
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_BEARER_POLICY in resp.text
        # Refused at the door, so the anonymous request this used to make never
        # leaves the process.
        probe.assert_not_awaited()

    async def test_a_whitespace_bearer_token_is_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """Refused by `_validate_safe_token`, which runs before the shape rule.

        Field validators run ahead of the model validator, so a token of spaces
        is answered by the whitespace rule that has always applied to this
        field rather than by the blank rule above. Recorded rather than
        asserted as the shape message, because which of the two answers first
        is a pydantic ordering detail and both are refusals.
        """
        resp, probe = await self._probe(
            client, admin_auth_header, {"auth": {"method": "bearer", "token": "   "}}
        )
        assert resp.status_code == 422, resp.text
        assert UNSUPPORTED_AUTH_METHOD_POLICY not in resp.text
        probe.assert_not_awaited()

    async def test_a_blank_basic_password_is_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        username = _opaque_value()
        resp, probe = await self._probe(
            client,
            admin_auth_header,
            {"auth": {"method": "basic", "username": username, "password": ""}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_BASIC_POLICY in resp.text
        assert username not in resp.text
        probe.assert_not_awaited()

    async def test_a_blank_header_value_is_refused(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        resp, probe = await self._probe(
            client,
            admin_auth_header,
            {
                "auth": {
                    "method": "header",
                    "header_name": "X-Api-Key",
                    "header_value": "   ",
                }
            },
        )
        assert resp.status_code == 422, resp.text
        # The SHAPE refusal, not `unsupported_auth_method`. These two fields
        # carry no field validator of their own, so this assertion is the only
        # thing separating "you left it blank" from "this method is not
        # available yet", and the second answer would send the caller off to
        # fix the wrong thing.
        assert SERVICE_AUTH_HEADER_POLICY in resp.text
        probe.assert_not_awaited()

    async def test_the_deprecated_flat_token_keeps_its_existing_meaning(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        """The alias is deliberately NOT tightened, because it never had the bug.

        `service_credential_from_request` builds a bearer credential only from a
        truthy `token`, and before this branch every door read `request.token`
        through the same truthiness test. So `token: ""` has always meant "no
        credential" and still does. Refusing it here would be a new 422 for
        callers who are sending a field they leave empty, which is a break
        dressed up as a fix.
        """
        resp, probe = await self._probe(client, admin_auth_header, {"token": ""})

        assert resp.status_code == 200, resp.text
        assert probe.await_args.kwargs["credential"] is None

    def test_the_gate_refuses_a_blank_bearer_credential_with_no_http_layer(
        self,
    ) -> None:
        """The direct path of plan D2, which no pydantic model guards."""
        from fastapi import HTTPException

        for blank in (None, "", "   "):
            with pytest.raises(HTTPException) as excinfo:
                bearer_token_for_credential(
                    ServiceCredential(
                        method=CredentialMethod.BEARER,
                        service_format="wfs",
                        token=blank,
                    )
                )
            assert excinfo.value.status_code == 422
            assert excinfo.value.detail["code"] == BLANK_BEARER_TOKEN_CODE

    def test_the_blank_credential_message_cannot_grow_an_interpolation(self) -> None:
        assert "{" not in BLANK_BEARER_TOKEN_POLICY


# ---------------------------------------------------------------------------
# Door 5: import commit (POST /ingest/commit/{job_id})
# ---------------------------------------------------------------------------


class TestImportCommitDoor:
    """feat(#1746 B2b): the door the first four left bearer-only.

    Without it a basic-protected WFS layer could be probed and previewed and
    then not imported, which is the shape of failure the closed door in #1760
    exists to avoid: the commit would have fetched anonymously and reported the
    origin's 401 as a broken service.

    ``ServiceCommitRequest`` is re-validated from the flat ``CommitRequest``'s
    dump, so the field has to be on both models or it is dropped before the
    subclass sees it. Both are asserted.
    """

    async def _job(self, session, *, created_by: uuid.UUID) -> IngestJob:
        job = IngestJob(
            source_filename="Parcels",
            source_url=_WFS_URL,
            source_layer="topp:parcels",
            created_by=created_by,
            status="pending",
            user_metadata={"service_type": "WFS 2.0.0", "layer_id": None},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def _post(self, client, session, headers, body: dict):
        admin_id = await get_user_id(session, "admin")
        job = await self._job(session, created_by=admin_id)
        task = AsyncMock()
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch("app.processing.ingest.tasks.ingest_service") as ingest_service,
        ):
            ingest_service.defer_async = task
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", **body},
                headers=headers,
            )
        return resp, task, job

    @pytest.mark.parametrize("builder", [_basic_auth, _header_auth])
    async def test_a_basic_commit_reaches_the_queue_as_one_composed_line(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        no_credential_store,  # noqa: F811
        builder,
    ) -> None:
        """The durable-argument install, so the wire value is readable here.

        With no credential store configured the door dispatches the value
        itself, which is what makes "one composed header line under the
        `token` kwarg, and nothing else" assertable end to end.
        """
        auth, secrets = builder()
        resp, task, _ = await self._post(
            client, test_db_session, admin_auth_header, {"auth": auth}
        )

        assert resp.status_code == 202, resp.text
        kwargs = task.await_args.kwargs
        line = kwargs["token"]
        assert line.count(": ") == 1
        assert line.startswith(
            "Authorization: Basic " if "username" in auth else "X-Api-Key: "
        )
        assert kwargs["credential_ref"] is None
        # Nothing else on the wire carries any part of it: for basic the
        # password is inside the blob and never appears raw.
        for secret in secrets:
            assert secret not in str({k: v for k, v in kwargs.items() if k != "token"})
        if "username" in auth:
            assert auth["password"] not in line

    async def test_a_bearer_commit_is_unchanged(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        no_credential_store,  # noqa: F811
    ) -> None:
        """The two spellings mean the same thing at this door too."""
        secret = _bearer_secret()
        flat_resp, flat_task, _ = await self._post(
            client, test_db_session, admin_auth_header, {"token": secret}
        )
        auth_resp, auth_task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "bearer", "token": secret}},
        )

        assert flat_resp.status_code == 202, flat_resp.text
        assert auth_resp.status_code == 202, auth_resp.text
        assert auth_task.await_args.kwargs["token"] == f"Authorization: Bearer {secret}"
        # Everything the credential decides, compared: the two calls run
        # against two job rows, which differ by id and by nothing else here.
        credential_kwargs = ("token", "credential_ref")
        assert {k: auth_task.await_args.kwargs[k] for k in credential_kwargs} == {
            k: flat_task.await_args.kwargs[k] for k in credential_kwargs
        }

    async def test_both_spellings_at_once_are_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        secret = _bearer_secret()
        resp, task, _ = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"token": secret, "auth": {"method": "bearer", "token": secret}},
        )
        assert resp.status_code == 422, resp.text
        assert SERVICE_AUTH_CONFLICT_POLICY in resp.text
        task.assert_not_awaited()

    async def test_a_blank_password_is_refused_before_any_job_row_changes(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """The refusal has to land before the metadata write, not after it.

        `service_auth_required` is a one-way door: `_replay_capability` reads
        it and refuses POST /jobs/{id}/retry. A credential refused after that
        write would leave a still-pending job that can never be replayed, for
        a request that queued nothing at all.
        """
        username = _opaque_value()
        resp, task, job = await self._post(
            client,
            test_db_session,
            admin_auth_header,
            {"auth": {"method": "basic", "username": username, "password": ""}},
        )

        assert resp.status_code == 422, resp.text
        assert username not in resp.text
        task.assert_not_awaited()

        reloaded = (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.id == job.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert reloaded.status == "pending"
        assert "service_auth_required" not in (reloaded.user_metadata or {})
        assert username not in str(reloaded.user_metadata)

    async def test_a_method_the_origin_cannot_carry_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """An ArcGIS job: its credential goes into the URL, so a header cannot."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Parcels",
            source_url=_ARCGIS_URL,
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "ArcGIS FeatureServer", "layer_id": 0},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        auth, secrets = _basic_auth()
        task = AsyncMock()
        with (
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch("app.processing.ingest.tasks.ingest_service") as ingest_service,
        ):
            ingest_service.defer_async = task
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parcels", "auth": auth},
                headers=admin_auth_header,
            )

        _assert_unsupported_without_the_values(resp, secrets)
        task.assert_not_awaited()

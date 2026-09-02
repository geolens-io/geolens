"""feat(#1746): the structured ``auth`` request contract at the four service doors.

Every door that can be handed a credential for a remote service now accepts a
nested ``auth`` object saying HOW to present it, alongside the flat ``token``
field that has always meant a bearer credential. The four doors are probe,
service preview, re-upload commit and refresh.

Four properties, asserted per door because each can regress on its own:

- an ``auth`` object with method ``bearer`` reaches the layer underneath
  exactly as the flat ``token`` does, so the two spellings cannot drift;
- a body that sets both is refused, rather than one winning by an ordering
  nobody wrote down;
- an ``auth`` object whose fields do not match its method is refused, and the
  refusal names the rule and never the value the caller typed;
- ``basic`` and ``header`` parse and are then refused with 422
  ``unsupported_auth_method``, because no transport composes a header line for
  them yet. A closed door rather than a request that is accepted and then
  fetched unauthenticated, which fails at the origin with a 401 and reads like
  a credential problem rather than a missing feature.

The last class is the D2 constraint from the plan: the refresh dispatch
decision and the ingest queue both take a ``ServiceCredential`` as a parameter
in their own right, so a caller with no HTTP layer can pass one. Those tests
call the functions directly and never build a request.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.service_tokens import CredentialMethod, ServiceCredential
from app.modules.catalog.sources.schemas import (
    SERVICE_AUTH_BASIC_POLICY,
    SERVICE_AUTH_CONFLICT_POLICY,
    ProbeResponse,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh import credentials as creds
from app.platform.service_auth import (
    UNSUPPORTED_AUTH_METHOD_CODE,
    UNSUPPORTED_AUTH_METHOD_POLICY,
    bearer_token_for_credential,
)
from tests.factories import create_dataset, get_user_id
from tests.test_import_token_lease_1676 import _reupload_harness
from tests.test_service_refresh_1220 import (  # noqa: F401
    _dispatch_harness,
    _service_dataset,
    credential_backend,
)

pytestmark = pytest.mark.anyio

_WFS_URL = "https://services.example.test/geoserver/wfs"


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
    session, *, dataset_id: uuid.UUID, created_by: uuid.UUID
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Parcels",
        source_url=_WFS_URL,
        source_layer="topp:parcels",
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
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
    async def _post(self, client: AsyncClient, headers: dict, body: dict):
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
        assert auth_probe.await_args.kwargs["token"] == secret
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
    async def test_a_method_with_no_transport_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, builder
    ) -> None:
        auth, secrets = builder()
        resp, probe = await self._post(client, admin_auth_header, {"auth": auth})
        _assert_unsupported_without_the_values(resp, secrets)
        # Refused before the network, so an unsupported method never reaches
        # the origin as an anonymous request.
        probe.assert_not_awaited()


# ---------------------------------------------------------------------------
# Door 2: service preview (POST /services/preview)
# ---------------------------------------------------------------------------


class TestPreviewDoor:
    async def _post(self, client: AsyncClient, headers: dict, body: dict):
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
                    "url": _WFS_URL,
                    "service_type": "WFS 2.0.0",
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
        assert auth_preview.await_args.kwargs["token"] == secret
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
        resp, preview = await self._post(client, admin_auth_header, {"auth": auth})
        _assert_unsupported_without_the_values(resp, secrets)
        preview.assert_not_awaited()


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

    async def _post(self, client, session, headers, body: dict):
        admin_id = await get_user_id(session, "admin")
        dataset = await self._dataset(session, created_by=admin_id)
        job = await _wfs_reupload_job(
            session, dataset_id=dataset.id, created_by=admin_id
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
        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

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
            client, test_db_session, admin_auth_header, {"auth": auth}
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


# ---------------------------------------------------------------------------
# Door 4: refresh (POST /datasets/{id}/refresh)
# ---------------------------------------------------------------------------


class TestRefreshDoor:
    async def _post(self, client, session, headers, body: dict):
        admin_id = await get_user_id(session, "admin")
        dataset = await _service_dataset(session, created_by=admin_id)
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
        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

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
            client, test_db_session, admin_auth_header, {"auth": auth}
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
        assert await creds.claim_service_credential(ref) == secret

    async def test_the_refresh_dispatch_service_refuses_a_method_with_no_transport(
        self,
        credential_backend,  # noqa: F811
    ) -> None:
        from fastapi import HTTPException

        password = _opaque_value()
        credential = ServiceCredential(
            method=CredentialMethod.BASIC,
            service_format="wfs",
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
        assert await creds.claim_service_credential(kwargs["credential_ref"]) == secret

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
            source_url=_WFS_URL,
            source_layer="topp:parcels",
            created_by=admin_id,
            status="pending",
            user_metadata={"service_type": "WFS 2.0.0", "layer_id": None},
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
                    service_format="wfs",
                    header_name="X-Api-Key",
                    header_value=value,
                ),
            )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == UNSUPPORTED_AUTH_METHOD_CODE
        assert value not in str(excinfo.value.detail)

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

    Stated for all four models rather than only the one that broke, because the
    same insertion is available in each and nothing else notices it.
    """

    def test_every_model_declares_auth_last(self) -> None:
        from app.modules.catalog.datasets.domain.schemas import (
            DatasetRefreshRequest,
            ReuploadCommitRequest,
        )
        from app.modules.catalog.sources.schemas import (
            ProbeRequest,
            ServicePreviewRequest,
        )

        for model in (
            ProbeRequest,
            ServicePreviewRequest,
            ReuploadCommitRequest,
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

"""A URL import keeps a durable, credential-free marker on its job row."""

import json

from httpx import AsyncClient
from sqlalchemy import update

from app.platform.jobs.models import IngestJob
from tests.test_url_import_async_1710 import (
    GEOJSON,
    _accept_any_url,
    _capture_defer,
    _get_job,
    _install_body,
    _run_task,
)

SIGNED_URL = (
    "https://user:hunter2@files.example.test/data/roads-2586.geojson"
    "?X-Amz-Signature=sigsecret&AWSAccessKeyId=akid-secret&Expires=99&se=sas-secret"
    "#frag-secret"
)
SECRETS = ("hunter2", "sigsecret", "akid-secret", "sas-secret", "frag-secret")


async def _queue(client, headers, monkeypatch, url):
    monkeypatch.setattr(
        "app.platform.security.validate_url_for_ssrf", _accept_any_url()
    )
    captured = _capture_defer(monkeypatch)
    resp = await client.post("/ingest/upload/url", json={"url": url}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp, captured


async def _admin_listing(client, headers, filename):
    resp = await client.get(
        "/admin/jobs/", params={"search": filename}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp


class TestUrlImportMarker:
    async def test_the_stored_url_is_credential_free(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """Userinfo, signed query values and the fragment never reach the row.

        Counterfactual: storing `redact_url_credentials(url)` alone keeps the
        unlisted `AWSAccessKeyId` and `se` values.
        """
        resp, _ = await _queue(client, admin_auth_header, monkeypatch, SIGNED_URL)
        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)

        assert job.user_metadata["url_import"] == (
            "https://files.example.test/data/roads-2586.geojson"
        )
        persisted = json.dumps(
            [job.user_metadata, job.source_url, job.error_message, job.file_path]
        )
        assert not any(secret in persisted for secret in SECRETS)
        assert not any(secret in resp.text for secret in SECRETS)

    async def test_the_marker_survives_staging(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The staged transition drops the in-flight marker but keeps this one.

        Counterfactual: adding the key to the transition's dropped set loses it.
        """
        resp, captured = await _queue(
            client, admin_auth_header, monkeypatch, SIGNED_URL
        )
        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])

        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        assert job.status == "pending"
        assert "url_download_in_flight" not in job.user_metadata
        assert job.user_metadata["url_import"].startswith("https://files.example.test/")

    async def test_a_failure_after_staging_with_the_file_gone_offers_start_again(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """The listing names the URL tab and a prefill URL without credentials.

        Counterfactual: classifying on the in-flight marker alone yields no
        restart source once staging has cleared it.
        """
        resp, captured = await _queue(
            client, admin_auth_header, monkeypatch, SIGNED_URL
        )
        _install_body(monkeypatch, GEOJSON)
        await _run_task(captured[0])
        job = await _get_job(test_db_session, resp.json()["job_id"])
        await test_db_session.refresh(job)
        staged = job.file_path
        await test_db_session.execute(
            update(IngestJob).where(IngestJob.id == job.id).values(status="failed")
        )
        await test_db_session.commit()
        from pathlib import Path

        Path(staged).unlink(missing_ok=True)

        listing = await _admin_listing(client, admin_auth_header, job.source_filename)
        (listed,) = [j for j in listing.json()["jobs"] if j["id"] == str(job.id)]
        assert listed["can_retry"] is False
        assert listed["restart_source"] == "url"
        assert (
            listed["source_url"] == "https://files.example.test/data/roads-2586.geojson"
        )
        assert not any(secret in listing.text for secret in SECRETS)

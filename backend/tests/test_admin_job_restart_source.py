"""The admin job list says where a failed, unretryable import can be started again."""

import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.platform.jobs.models import IngestJob
from tests.factories import get_user_id

SECRET_URL = (
    "https://user:hunter2@maps.example.com/arcgis/rest/services/Roads/FeatureServer"
    "?f=json&token=s3cr3t&layer=3"
)


async def _listed(client, headers, session, **fields):
    filename = f"restart{uuid.uuid4().hex[:10]}"
    job = IngestJob(
        created_by=await get_user_id(session, "admin"),
        source_filename=filename,
        **fields,
    )
    session.add(job)
    await session.commit()
    try:
        resp = await client.get(
            "/admin/jobs/", params={"search": filename}, headers=headers
        )
    finally:
        await session.execute(delete(IngestJob).where(IngestJob.id == job.id))
        await session.commit()
    assert resp.status_code == 200, resp.text
    (listed,) = resp.json()["jobs"]
    return listed


async def test_a_refused_service_import_lists_its_redacted_url(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Userinfo and credential query values never reach the list response."""
    listed = await _listed(
        client,
        admin_auth_header,
        test_db_session,
        status="failed",
        source_url=SECRET_URL,
        user_metadata={
            "service_type": "ArcGIS FeatureServer",
            "service_auth_required": True,
        },
    )

    assert listed["can_retry"] is False
    assert listed["restart_source"] == "service"
    assert "hunter2" not in listed["source_url"]
    assert "s3cr3t" not in listed["source_url"]
    assert (
        "maps.example.com/arcgis/rest/services/Roads/FeatureServer"
        in listed["source_url"]
    )


async def test_an_unfinished_url_download_restarts_from_the_url_tab(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A URL import keeps no URL on the row, so only the tab is named."""
    listed = await _listed(
        client,
        admin_auth_header,
        test_db_session,
        status="failed",
        file_path="",
        user_metadata={"url_download_in_flight": True},
    )

    assert (listed["restart_source"], listed["source_url"]) == ("url", None)


async def test_a_job_that_can_be_retried_or_is_not_failed_has_no_restart_source(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Retry stays the action when it works, and a live job has nothing to restart."""
    retryable = await _listed(
        client,
        admin_auth_header,
        test_db_session,
        status="failed",
        source_url="https://maps.example.com/wfs",
    )
    running = await _listed(
        client,
        admin_auth_header,
        test_db_session,
        status="running",
        file_path="",
        user_metadata={"url_download_in_flight": True},
    )

    assert retryable["can_retry"] is True
    assert retryable["restart_source"] is None
    assert running["restart_source"] is None

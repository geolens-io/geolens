"""Egress contract of the ArcGIS portal client, and the SDK transport fake."""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

import pytest

from geolens_cli import arcgis_inventory as inventory
from geolens_cli.arcgis_portal import NO_FILE, PortalError
from geolens_cli.main import app

from .arcgis_fake import NO_FILE_PAGE, PORTAL, FakePortal, portal_routes
from .conftest import GEOLENS_INSTANCE

USER_ID = "00000000-0000-0000-0000-000000000301"


def _hosts(urls) -> set[str | None]:
    return {urlsplit(url).hostname for url in urls}


def test_fake_geolens_records_sdk_requests_with_their_host(runner, fake_geolens):
    fake_geolens.routes["GET /auth/me/"] = {
        "id": USER_ID,
        "username": "operator",
        "email": "operator@example.org",
        "is_active": True,
        "status": "active",
        "last_login_at": None,
        "created_at": "2026-10-01T00:00:00Z",
        "roles": ["admin"],
        "can_reset_password": False,
    }

    result = runner.invoke(app, ["--json", "whoami"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["email"] == "operator@example.org"
    [seen] = fake_geolens.seen
    assert _hosts([seen.url]) == _hosts([GEOLENS_INSTANCE])
    assert seen.headers["authorization"] == f"Bearer {fake_geolens.token}"


def test_inventory_requests_reach_only_the_portal_and_geolens(
    runner, monkeypatch, fake_geolens
):
    portal = FakePortal(portal_routes())
    monkeypatch.setattr(inventory, "build_opener", lambda: portal)
    monkeypatch.setattr(inventory, "_sleep", lambda seconds: None)
    monkeypatch.delenv("ARCGIS_PASSWORD", raising=False)
    token = secrets.token_urlsafe(24)

    result = runner.invoke(
        app,
        ["--json", "arcgis", "inventory", "--portal-url", PORTAL, "--token", token],
    )

    assert result.exit_code == 0, result.output
    allowed = _hosts([PORTAL, GEOLENS_INSTANCE])
    item_urls = [row["url"] for row in json.loads(result.output)["items"] if row["url"]]
    # The fixture's items point at service hosts; reading any of them would
    # show up below as a third host.
    assert _hosts(item_urls) - allowed
    assert portal.seen
    assert _hosts(s.url for s in [*portal.seen, *fake_geolens.seen]) <= allowed


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (NO_FILE_PAGE, NO_FILE),
        (
            (200, {"error": {"code": 500, "message": "Item does not have a file."}}),
            NO_FILE,
        ),
        ((500, b"<html><title>Internal Server Error</title></html>"), "server"),
        (
            (200, {"error": {"code": 500, "message": "Unable to read the item."}}),
            "server",
        ),
    ],
)
def test_only_the_no_file_answer_is_read_as_an_item_without_a_file(
    tmp_path, reply, kind
):
    """Only a 500 saying the item has no file gets the no-file kind."""
    path = "content/items/" + "ab" * 16 + "/data"
    portal = FakePortal({path: reply})
    client = inventory.PortalClient(
        PORTAL,
        opener=portal,
        redact=inventory.Redactor(),
        token="t",
        sleep=lambda s: None,
    )

    with pytest.raises(PortalError) as raised:
        client.download(path, tmp_path / "data", None)

    assert raised.value.kind == kind
    assert raised.value.http_status == 500

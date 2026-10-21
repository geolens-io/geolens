"""Egress contract of the ArcGIS portal client, and the SDK transport fake."""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlsplit

from geolens_cli import arcgis_inventory as inventory
from geolens_cli.main import app

from .arcgis_fake import PORTAL, FakePortal, portal_routes
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

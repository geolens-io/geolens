"""Integration tests for config export, import (merge/overwrite), and dry-run.

Tests cover: export shape and secret redaction, import merge and overwrite modes,
dry-run diff without DB writes, permission matrix validation, and auth enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_export_config(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /config-ops/export/ returns 200 with expected shape."""
    resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "exported_at" in data
    assert "settings" in data
    assert isinstance(data["settings"], dict)
    assert "oauth_providers" in data
    assert isinstance(data["oauth_providers"], list)
    # Should contain known settings
    assert "log_level" in data["settings"]
    assert "registration_enabled" in data["settings"]


@pytest.mark.anyio
async def test_export_redacts_secrets(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Exported OAuth providers must not contain client_secret or client_secret_encrypted."""
    resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    for provider in data["oauth_providers"]:
        assert "client_secret" not in provider
        assert "client_secret_encrypted" not in provider


@pytest.mark.anyio
async def test_export_requires_auth(client: AsyncClient):
    """Unauthenticated request to export returns 401."""
    resp = await client.get("/config-ops/export/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_export_requires_manage_settings(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer (no manage_settings) gets 403."""
    resp = await client.get("/config-ops/export/", headers=viewer_auth_header)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_import_merge(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /config-ops/import/?mode=merge applies changed setting values."""
    # Get current config
    export_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert export_resp.status_code == 200
    config = export_resp.json()

    # Modify a setting
    original_log_level = config["settings"]["log_level"]
    new_log_level = "DEBUG" if original_log_level != "DEBUG" else "WARNING"
    config["settings"]["log_level"] = new_log_level

    # Import in merge mode
    import_resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": config["settings"]},
        headers=admin_auth_header,
    )
    assert import_resp.status_code == 200
    result = import_resp.json()
    assert result["settings_applied"] > 0

    # Verify the change took effect
    verify_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["settings"]["log_level"] == new_log_level

    # Restore original
    await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"log_level": original_log_level}},
        headers=admin_auth_header,
    )


@pytest.mark.anyio
async def test_import_overwrite(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /config-ops/import/?mode=overwrite replaces settings."""
    # Export current to restore later
    export_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert export_resp.status_code == 200
    original = export_resp.json()

    # Import overwrite with a subset of settings
    import_resp = await client.post(
        "/config-ops/import/?mode=overwrite",
        json={"settings": original["settings"]},
        headers=admin_auth_header,
    )
    assert import_resp.status_code == 200
    result = import_resp.json()
    assert result["settings_applied"] > 0


@pytest.mark.anyio
async def test_import_validates_permissions_matrix(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Import with invalid role_permissions returns 422."""
    # Try to remove manage_settings from admin (lockout)
    bad_permissions = {
        "admin": {
            "manage_users": True,
            "manage_settings": False,  # This should fail validation
        }
    }
    import_resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"role_permissions": bad_permissions}},
        headers=admin_auth_header,
    )
    assert import_resp.status_code == 422


@pytest.mark.anyio
async def test_import_skips_unknown_keys(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Import with unknown setting keys skips them without error."""
    import_resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"nonexistent_future_key": "value123"}},
        headers=admin_auth_header,
    )
    assert import_resp.status_code == 200
    result = import_resp.json()
    assert result["settings_skipped"] == 1
    assert result["settings_applied"] == 0


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dry_run_no_changes(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Dry-run with current values shows all no_change."""
    # Export current config
    export_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    config = export_resp.json()

    # Dry-run with same values
    dry_resp = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": config["settings"]},
        headers=admin_auth_header,
    )
    assert dry_resp.status_code == 200
    data = dry_resp.json()
    assert "settings" in data
    assert "changes" in data["settings"]

    # All should be no_change
    for change in data["settings"]["changes"]:
        assert change["action"] == "no_change", (
            f"Expected no_change for {change['key']}, got {change['action']}"
        )


@pytest.mark.anyio
async def test_dry_run_with_changes(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Dry-run with modified values shows update actions."""
    export_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    config = export_resp.json()

    # Modify a setting
    original = config["settings"]["log_level"]
    modified = "DEBUG" if original != "DEBUG" else "WARNING"
    config["settings"]["log_level"] = modified

    dry_resp = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": config["settings"]},
        headers=admin_auth_header,
    )
    assert dry_resp.status_code == 200
    data = dry_resp.json()

    # Find the log_level change
    log_level_changes = [
        c for c in data["settings"]["changes"] if c["key"] == "log_level"
    ]
    assert len(log_level_changes) == 1
    assert log_level_changes[0]["action"] == "update"
    assert log_level_changes[0]["imported"] == modified


@pytest.mark.anyio
async def test_dry_run_does_not_modify_db(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Values remain unchanged after a dry-run."""
    # Get current state
    before_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    before = before_resp.json()

    # Dry-run with modifications
    modified_settings = dict(before["settings"])
    original_level = modified_settings["log_level"]
    modified_settings["log_level"] = "CRITICAL"

    await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": modified_settings},
        headers=admin_auth_header,
    )

    # Verify nothing changed
    after_resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    after = after_resp.json()
    assert after["settings"]["log_level"] == original_level


# ---------------------------------------------------------------------------
# Connectivity validation tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_connectivity(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /config-ops/validate/ returns 200 with storage, cache, oidc_providers keys."""
    resp = await client.post("/config-ops/validate/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "storage" in data
    assert "cache" in data
    assert "oidc_providers" in data
    # Check storage shape
    assert "name" in data["storage"]
    assert "status" in data["storage"]
    assert "latency_ms" in data["storage"]
    # Check cache shape
    assert "name" in data["cache"]
    assert "status" in data["cache"]
    assert "latency_ms" in data["cache"]


@pytest.mark.anyio
async def test_validate_requires_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer (no manage_settings) gets 403."""
    resp = await client.post("/config-ops/validate/", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_validate_requires_auth(client: AsyncClient):
    """Unauthenticated request returns 401."""
    resp = await client.post("/config-ops/validate/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_validate_oidc_empty(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """When no OAuth providers configured, oidc_providers is empty dict."""
    resp = await client.post("/config-ops/validate/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["oidc_providers"] == {}


# ---------------------------------------------------------------------------
# Auth enforcement tests for import and dry-run
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_import_requires_auth(client: AsyncClient):
    """Unauthenticated request to import returns 401."""
    resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"log_level": "INFO"}},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_import_requires_manage_settings(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer (no manage_settings) importing config gets 403."""
    resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"log_level": "INFO"}},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_dry_run_requires_auth(client: AsyncClient):
    """Unauthenticated request to dry-run returns 401."""
    resp = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": {"log_level": "INFO"}},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_dry_run_requires_manage_settings(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer (no manage_settings) dry-run gets 403."""
    resp = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": {"log_level": "INFO"}},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403

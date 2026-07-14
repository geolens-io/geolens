"""Integration tests for config export, import (merge/overwrite), and dry-run.

Tests cover: export shape and secret redaction, import merge and overwrite modes,
dry-run diff without DB writes, permission matrix validation, and auth enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import asyncio
import base64
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select


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
async def test_export_config_is_audited_with_actor_and_ip(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A sensitive configuration export is durable in the audit log."""
    from app.modules.audit.models import AuditLog

    resp = await client.get("/config-ops/export/", headers=admin_auth_header)
    assert resp.status_code == 200

    result = await test_db_session.execute(
        select(AuditLog)
        .where(AuditLog.action == "config_export")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    event = result.scalar_one()
    assert event.user_id is not None
    assert event.ip_address is not None
    assert event.details["settings_count"] > 0


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
        assert "idp_certificate" not in provider


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
    assert import_resp.status_code == 200, f"Config import failed: {import_resp.json()}"
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

    # A destructive apply must be bound to its exact dry-run.
    preview_resp = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={"settings": original["settings"]},
        headers=admin_auth_header,
    )
    assert preview_resp.status_code == 200
    preview_token = preview_resp.json()["preview_token"]

    import_resp = await client.post(
        "/config-ops/import/?mode=overwrite",
        json={"settings": original["settings"]},
        headers={**admin_auth_header, "X-Config-Preview-Token": preview_token},
    )
    assert import_resp.status_code == 200, f"Config import failed: {import_resp.json()}"
    result = import_resp.json()
    expected_applied = sum(
        change["action"] == "update"
        for change in preview_resp.json()["settings"]["changes"]
    )
    assert result["settings_applied"] == expected_applied


@pytest.mark.anyio
async def test_import_overwrite_requires_matching_preview(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Missing and payload-switched overwrite confirmations are rejected."""
    data = {"settings": {"log_level": "DEBUG"}}
    missing = await client.post(
        "/config-ops/import/?mode=overwrite",
        json=data,
        headers=admin_auth_header,
    )
    assert missing.status_code == 409
    malformed = await client.post(
        "/config-ops/import/?mode=overwrite",
        json=data,
        headers={**admin_auth_header, "X-Config-Preview-Token": "not-a-token"},
    )
    assert malformed.status_code == 409

    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json=data,
        headers=admin_auth_header,
    )
    assert preview.status_code == 200
    token = preview.json()["preview_token"]
    switched = await client.post(
        "/config-ops/import/?mode=overwrite",
        json={"settings": {"log_level": "WARNING"}},
        headers={**admin_auth_header, "X-Config-Preview-Token": token},
    )
    assert switched.status_code == 409


@pytest.mark.anyio
async def test_import_overwrite_rejects_preview_after_state_change(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """A preview cannot be applied after relevant configuration state changes."""
    export = await client.get("/config-ops/export/", headers=admin_auth_header)
    current = export.json()["settings"]
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={"settings": current},
        headers=admin_auth_header,
    )
    assert preview.status_code == 200

    original = current["registration_enabled"]
    changed = await client.put(
        "/settings/",
        json={"settings": {"registration_enabled": not original}},
        headers=admin_auth_header,
    )
    assert changed.status_code == 200
    try:
        apply = await client.post(
            "/config-ops/import/?mode=overwrite",
            json={"settings": current},
            headers={
                **admin_auth_header,
                "X-Config-Preview-Token": preview.json()["preview_token"],
            },
        )
        assert apply.status_code == 409
    finally:
        await client.put(
            "/settings/",
            json={"settings": {"registration_enabled": original}},
            headers=admin_auth_header,
        )


@pytest.mark.anyio
async def test_overwrite_import_enforces_final_login_method_invariant(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Preview and locked apply reject zero methods and accept enabled SSO."""
    lockout_payload = {
        "settings": {"password_login_enabled": False},
        "oauth_providers": [],
    }
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json=lockout_payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=overwrite",
        json=lockout_payload,
        headers=admin_auth_header,
    )
    assert preview.status_code == 422
    assert apply.status_code == 422
    assert "every login method" in preview.json()["detail"]
    assert preview.json()["detail"] == apply.json()["detail"]

    valid = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={
            "settings": {"password_login_enabled": False},
            "oauth_providers": [
                {
                    "slug": f"lockout-safe-{uuid.uuid4().hex[:8]}",
                    "display_name": "Lockout-safe provider",
                    "provider_type": "oidc",
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
                    "enabled": True,
                }
            ],
        },
        headers=admin_auth_header,
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["preview_token"]


@pytest.mark.anyio
async def test_overwrite_preview_reports_dependent_oauth_account_deletions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Provider previews expose only exact link counts and bind link state."""
    from app.core.config import settings
    from app.modules.auth.models import User
    from app.modules.auth.oauth.encryption import encrypt_secret
    from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider

    admin_id = await test_db_session.scalar(
        select(User.id).where(User.username == settings.geolens_admin_username)
    )
    provider = OAuthProvider(
        slug=f"account-preview-{uuid.uuid4().hex[:8]}",
        display_name="Account preview provider",
        provider_type="oidc",
        client_id="client-id",
        client_secret_encrypted=encrypt_secret("client-secret"),
        discovery_url="https://idp.example.com/.well-known/openid-configuration",
        scopes="openid profile email",
        default_role="viewer",
        enabled=True,
    )
    test_db_session.add(provider)
    await test_db_session.flush()
    subject = f"subject-must-stay-private-{uuid.uuid4().hex}"
    test_db_session.add(
        OAuthAccount(
            provider_id=provider.id,
            user_id=admin_id,
            subject=subject,
        )
    )
    await test_db_session.commit()
    try:
        preview = await client.post(
            "/config-ops/dry-run/?mode=overwrite",
            json={"settings": {}, "oauth_providers": []},
            headers=admin_auth_header,
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        change = next(
            item
            for item in body["oauth_providers"]["changes"]
            if item["slug"] == provider.slug
        )
        assert change["action"] == "delete"
        assert change["dependent_accounts_deleted"] == 1
        assert body["oauth_providers"]["dependent_accounts_deleted"] >= 1

        encoded_claims = body["preview_token"].split(".", 1)[0]
        encoded_claims += "=" * (-len(encoded_claims) % 4)
        claims = json.loads(base64.urlsafe_b64decode(encoded_claims))
        assert subject not in json.dumps(claims)
    finally:
        await test_db_session.delete(provider)
        await test_db_session.commit()


@pytest.mark.anyio
async def test_config_import_lock_serializes_concurrent_setting_write(
    client: AsyncClient,
    monkeypatch,
):
    """The import write fence blocks a settings commit until import releases."""
    import app.core.db as db_module
    from app.core.db.models import AppSetting
    from app.core.persistent_config import LOG_LEVEL
    from app.platform.config_ops.service import acquire_config_import_lock

    async with db_module.async_session() as snapshot_session:
        result = await snapshot_session.execute(
            select(AppSetting.value).where(AppSetting.key == LOG_LEVEL.key)
        )
        had_override = result.scalar_one_or_none() is not None
        original = await LOG_LEVEL.get_uncached(snapshot_session)

    target = "DEBUG" if original != "DEBUG" else "WARNING"
    writer_task = None
    try:
        async with (
            db_module.async_session() as import_session,
            db_module.async_session() as writer_session,
        ):
            await acquire_config_import_lock(import_session)

            commit_started = asyncio.Event()
            original_commit = writer_session.commit

            async def tracked_commit():
                commit_started.set()
                await original_commit()

            monkeypatch.setattr(writer_session, "commit", tracked_commit)
            writer_task = asyncio.create_task(LOG_LEVEL.set(writer_session, target))
            await asyncio.wait_for(commit_started.wait(), timeout=2)

            # The writer reached COMMIT but PostgreSQL cannot grant its DML table
            # lock while the import transaction holds EXCLUSIVE mode.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(writer_task), timeout=0.1)

            await import_session.rollback()
            await asyncio.wait_for(writer_task, timeout=2)
            writer_task = None
    finally:
        if writer_task is not None:
            await asyncio.gather(writer_task, return_exceptions=True)
        async with db_module.async_session() as restore_session:
            if had_override:
                await LOG_LEVEL.set(restore_session, original)
            else:
                await LOG_LEVEL.reset(restore_session)


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
async def test_import_rejects_admin_manage_tenants_escalation(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Config import shares the out-of-band-only fleet capability invariant."""
    import_resp = await client.post(
        "/config-ops/import/?mode=merge",
        json={
            "settings": {
                "role_permissions": {
                    "admin": {
                        "manage_users": True,
                        "manage_settings": True,
                        "manage_tenants": True,
                    }
                }
            }
        },
        headers=admin_auth_header,
    )
    assert import_resp.status_code == 422
    assert "manage_tenants" in import_resp.json()["detail"]


@pytest.mark.anyio
async def test_import_rejects_coerced_false_admin_capabilities(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Config preflight checks the canonical permission matrix after coercion."""
    response = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={
            "settings": {
                "role_permissions": {
                    "admin": {
                        "manage_users": "false",
                        "manage_settings": "false",
                    }
                }
            }
        },
        headers=admin_auth_header,
    )

    assert response.status_code == 422
    assert "lockout" in response.json()["detail"]


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


@pytest.mark.anyio
async def test_import_and_dry_run_share_type_validation(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Both paths reject values outside the setting's registered type."""
    payload = {"settings": {"ai_enabled": {"not": "a boolean"}}}
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    assert preview.status_code == 422
    assert apply.status_code == 422
    assert "ai_enabled" in preview.json()["detail"]


@pytest.mark.anyio
async def test_import_and_dry_run_share_oauth_schema_validation(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Malformed OAuth creates fail during preview, before any apply."""
    payload = {
        "oauth_providers": [
            {
                "slug": "invalid provider slug",
                "display_name": "Invalid",
                "provider_type": "oidc",
            }
        ]
    }
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    assert preview.status_code == 422
    assert apply.status_code == 422


@pytest.mark.anyio
async def test_import_and_dry_run_share_oauth_security_validation(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Service-level endpoint invariants reject the same plan on both paths."""
    payload = {
        "oauth_providers": [
            {
                "slug": "mixed-endpoints",
                "display_name": "Mixed endpoints",
                "provider_type": "oidc",
                "client_id": "client-id",
                "client_secret": "client-secret",
                "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
                "token_url": "https://idp.example.com/token",
            }
        ]
    }
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )

    assert preview.status_code == 422
    assert apply.status_code == 422
    assert "either discovery or explicit" in preview.json()["detail"]
    assert preview.json()["detail"] == apply.json()["detail"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("key", "value", "secret_fragment"),
    [
        ("log_level", "SECRET-LOG-LEVEL-INPUT", "SECRET-LOG-LEVEL-INPUT"),
        (
            "ai_enabled",
            {"api_key": "sk-secret-type-adapter-input"},
            "sk-secret-type-adapter-input",
        ),
    ],
)
async def test_config_setting_validation_errors_redact_submitted_values(
    key: str,
    value,
    secret_fragment: str,
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Custom and TypeAdapter failures return only a known setting field."""
    payload = {"settings": {key: value}}
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )

    assert preview.status_code == 422
    assert apply.status_code == 422
    for response in (preview, apply):
        detail = response.json()["detail"]
        assert key in detail
        assert secret_fragment not in detail
        assert "api_key" not in detail


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"settings": "top-level-settings-secret"},
        {"oauth_providers": "top-level-provider-secret"},
        {"oauth_providers": ["provider-entry-secret"]},
    ],
)
async def test_config_shape_validation_errors_do_not_reflect_input(
    payload,
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Request shape failures are routed through sanitized service errors."""
    serialized = json.dumps(payload)
    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )

    assert preview.status_code == 422
    assert apply.status_code == 422
    for response in (preview, apply):
        detail = response.json()["detail"]
        for secret in (
            "top-level-settings-secret",
            "top-level-provider-secret",
            "provider-entry-secret",
        ):
            if secret in serialized:
                assert secret not in detail


@pytest.mark.anyio
async def test_config_provider_schema_errors_redact_credentials_and_inputs(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Pydantic provider failures expose field names, not model input values."""
    secret = "oauth-client-secret-must-never-appear"
    invalid_display = "invalid-display-input-must-never-appear"
    payload = {
        "oauth_providers": [
            {
                "slug": "redaction-test",
                "display_name": {"value": invalid_display},
                "provider_type": "oidc",
                "client_id": "client-id",
                "client_secret": secret,
                "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
            }
        ]
    }

    preview = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )
    apply = await client.post(
        "/config-ops/import/?mode=merge",
        json=payload,
        headers=admin_auth_header,
    )

    assert preview.status_code == 422
    assert apply.status_code == 422
    for response in (preview, apply):
        detail = response.json()["detail"]
        assert "display_name" in detail
        assert secret not in detail
        assert invalid_display not in detail
        assert "redaction-test" not in detail


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["merge", "overwrite"])
async def test_default_equal_payload_is_previewed_as_source_update(
    mode: str,
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """An explicit env-default value pins a new override in either mode."""
    from app.core.db.models import AppSetting
    from app.core.persistent_config import LOG_LEVEL

    stored = await test_db_session.scalar(
        select(AppSetting.value).where(AppSetting.key == LOG_LEVEL.key)
    )
    had_override = stored is not None
    original = await LOG_LEVEL.get_uncached(test_db_session)
    await LOG_LEVEL.reset(test_db_session)
    try:
        preview = await client.post(
            f"/config-ops/dry-run/?mode={mode}",
            json={"settings": {LOG_LEVEL.key: LOG_LEVEL.env_default}},
            headers=admin_auth_header,
        )
        assert preview.status_code == 200, preview.text
        change = next(
            item
            for item in preview.json()["settings"]["changes"]
            if item["key"] == LOG_LEVEL.key
        )
        assert change["action"] == "update"
        assert "database override" in change["reason"]
    finally:
        if had_override:
            await LOG_LEVEL.set(test_db_session, original)
        else:
            await LOG_LEVEL.reset(test_db_session)


@pytest.mark.anyio
async def test_existing_equal_override_is_a_true_import_noop(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A no_change preview is not subsequently written or counted as applied."""
    from app.core.db.models import AppSetting
    from app.core.persistent_config import LOG_LEVEL

    stored = await test_db_session.scalar(
        select(AppSetting.value).where(AppSetting.key == LOG_LEVEL.key)
    )
    had_override = stored is not None
    original = await LOG_LEVEL.get_uncached(test_db_session)
    await LOG_LEVEL.set(test_db_session, LOG_LEVEL.env_default)
    try:
        preview = await client.post(
            "/config-ops/dry-run/?mode=merge",
            json={"settings": {LOG_LEVEL.key: LOG_LEVEL.env_default}},
            headers=admin_auth_header,
        )
        change = preview.json()["settings"]["changes"][0]
        assert change["action"] == "no_change"

        applied = await client.post(
            "/config-ops/import/?mode=merge",
            json={"settings": {LOG_LEVEL.key: LOG_LEVEL.env_default}},
            headers=admin_auth_header,
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["settings_applied"] == 0
        assert applied.json()["settings_skipped"] == 1
    finally:
        if had_override:
            await LOG_LEVEL.set(test_db_session, original)
        else:
            await LOG_LEVEL.reset(test_db_session)


@pytest.mark.anyio
async def test_default_equal_payload_repairs_invalid_stored_override(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Fallback equality does not hide an invalid database value needing repair."""
    from app.core.db.models import AppSetting
    from app.core.persistent_config import LOG_LEVEL

    row = await test_db_session.get(AppSetting, LOG_LEVEL.key)
    had_override = row is not None
    original_value = row.value if row is not None else None
    if row is None:
        row = AppSetting(key=LOG_LEVEL.key, value={"v": {"invalid": True}})
        test_db_session.add(row)
    else:
        row.value = {"v": {"invalid": True}}
    await test_db_session.commit()
    try:
        preview = await client.post(
            "/config-ops/dry-run/?mode=merge",
            json={"settings": {LOG_LEVEL.key: LOG_LEVEL.env_default}},
            headers=admin_auth_header,
        )
        assert preview.status_code == 200, preview.text
        change = preview.json()["settings"]["changes"][0]
        assert change["action"] == "update"
        assert "invalid database override" in change["reason"]
    finally:
        row = await test_db_session.get(AppSetting, LOG_LEVEL.key)
        if had_override:
            row.value = original_value
        else:
            await test_db_session.delete(row)
        await test_db_session.commit()


@pytest.mark.anyio
async def test_dry_run_no_changes(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Dry-run distinguishes true no-ops from source-pinning updates."""
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

    # Existing DB overrides are no-ops. Runtime defaults are explicit source
    # updates because apply will pin them into the database.
    for change in data["settings"]["changes"]:
        assert change["action"] in {"no_change", "update", "skip_restricted"}


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
async def test_overwrite_preview_lists_all_omitted_resets_and_skip_outcomes(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Overwrite previews expose resets plus unknown/restricted outcomes."""
    preview = await client.post(
        "/config-ops/dry-run/?mode=overwrite",
        json={
            "settings": {
                "log_level": "INFO",
                "future_setting": "kept-for-forward-compatibility",
                "branding.show_badge": False,
            }
        },
        headers=admin_auth_header,
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["preview_token"]
    changes = {change["key"]: change for change in data["settings"]["changes"]}
    assert changes["registration_enabled"]["action"] == "reset"
    assert changes["future_setting"]["action"] == "skip_unknown"
    assert changes["branding.show_badge"]["action"] == "skip_restricted"
    assert data["settings"]["skipped_unknown"] == ["future_setting"]
    assert data["settings"]["skipped_restricted"] == ["branding.show_badge"]


@pytest.mark.anyio
async def test_config_import_emits_one_aggregate_audit_event(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A successful batch commits one aggregate event with its per-key audits."""
    from app.modules.audit.models import AuditLog

    before = await test_db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "config_import")
    )
    response = await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"log_level": "INFO"}},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    assert response.json()["oauth_accounts_deleted"] == 0
    test_db_session.expire_all()
    after = await test_db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "config_import")
    )
    assert after == before + 1
    event = await test_db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "config_import")
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    assert event.details["oauth_accounts_deleted"] == 0


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
    test_db_session,
):
    """When no OAuth providers configured, oidc_providers is empty dict."""
    # The validate endpoint reads the GLOBAL provider set. Under `pytest -n`
    # each xdist worker shares one DB across its tests, and some sibling tests
    # create providers without cleaning them up (e.g. the audit-redaction and
    # SAML-conversion invariants), so a "must be empty" assertion is order-
    # dependent. Purge providers up-front for a deterministic slate — mirrors
    # _purge_all_oauth_providers in test_sso_login_mode.py.
    from sqlalchemy import delete as sa_delete

    from app.modules.auth.oauth.models import OAuthProvider

    await test_db_session.execute(sa_delete(OAuthProvider))
    await test_db_session.commit()

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

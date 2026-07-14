"""Unit tests for config_ops schemas and service (TDD RED phase)."""

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_schemas_importable():
    """Config ops schemas should be importable."""
    from app.platform.config_ops.schemas import (
        ConfigExportResponse,
        ConfigImportRequest,
        DryRunResponse,
        ImportResult,
        SettingChange,
        OAuthProviderChange,
    )

    assert ConfigExportResponse is not None
    assert ConfigImportRequest is not None
    assert DryRunResponse is not None
    assert ImportResult is not None
    assert SettingChange is not None
    assert OAuthProviderChange is not None


def test_service_importable():
    """Config ops service functions should be importable."""
    from app.platform.config_ops.service import (
        export_config,
        import_config,
        dry_run_import,
    )

    assert export_config is not None
    assert import_config is not None
    assert dry_run_import is not None


def test_config_export_response_shape():
    """ConfigExportResponse should accept version, exported_at, settings, oauth_providers."""
    from app.platform.config_ops.schemas import ConfigExportResponse

    resp = ConfigExportResponse(
        version="1.0",
        exported_at="2026-03-07T00:00:00Z",
        settings={"log_level": "INFO"},
        oauth_providers=[],
    )
    assert resp.version == "1.0"
    assert resp.settings == {"log_level": "INFO"}
    assert resp.oauth_providers == []


def test_config_import_request_defaults():
    """ConfigImportRequest fields should default to None."""
    from app.platform.config_ops.schemas import ConfigImportRequest

    req = ConfigImportRequest()
    assert req.settings is None
    assert req.oauth_providers is None


def test_import_result_shape():
    """ImportResult should track counts."""
    from app.platform.config_ops.schemas import ImportResult

    result = ImportResult(
        settings_applied=2,
        settings_skipped=1,
        oauth_created=0,
        oauth_updated=1,
        oauth_deleted=0,
    )
    assert result.settings_applied == 2
    assert result.settings_skipped == 1
    assert result.oauth_accounts_deleted == 0


def test_setting_change_shape():
    """SettingChange should have key, current, imported, action."""
    from app.platform.config_ops.schemas import SettingChange

    change = SettingChange(
        key="log_level",
        current="INFO",
        imported="DEBUG",
        action="update",
    )
    assert change.action == "update"


def test_oauth_provider_change_shape():
    """OAuthProviderChange should have slug, action, changed_fields."""
    from app.platform.config_ops.schemas import OAuthProviderChange

    change = OAuthProviderChange(
        slug="google",
        action="create",
        changed_fields=["client_id"],
    )
    assert change.action == "create"


def test_dry_run_response_shape():
    """DryRunResponse should have settings and oauth_providers sections."""
    from app.platform.config_ops.schemas import DryRunResponse

    resp = DryRunResponse(
        settings={"changes": []},
        oauth_providers={"changes": []},
    )
    assert resp.settings == {"changes": []}
    assert resp.oauth_providers == {"changes": []}


def test_config_preview_header_is_allowed_by_credentialed_cors():
    """A separate admin origin can send the overwrite confirmation header."""
    from starlette.responses import Response

    from app.api.middleware.cors import DynamicCORSMiddleware

    response = Response()
    DynamicCORSMiddleware._set_cors_headers(response, "https://admin.example.com")
    assert "X-Config-Preview-Token" in response.headers["Access-Control-Allow-Headers"]


def test_oauth_preflight_runs_service_level_endpoint_validation():
    """Dry-run rejects the same mixed endpoint mode as provider apply."""
    from app.platform.config_ops.exceptions import ConfigValidationError
    from app.platform.config_ops.service import _normalize_provider_payload

    with pytest.raises(ConfigValidationError, match="either discovery or explicit"):
        _normalize_provider_payload(
            [
                {
                    "slug": "mixed-endpoints",
                    "display_name": "Mixed endpoints",
                    "provider_type": "oidc",
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
                    "token_url": "https://idp.example.com/token",
                }
            ],
            {},
            "merge",
        )


def test_oauth_preflight_requires_secret_when_endpoint_destination_changes():
    """Dry-run enforces the same credential-destination guard as apply."""
    from app.platform.config_ops.exceptions import ConfigValidationError
    from app.platform.config_ops.service import _normalize_provider_payload

    existing = SimpleNamespace(
        slug="example",
        provider_type="oidc",
        discovery_url=None,
        authorize_url="https://idp.example.com/authorize",
        token_url="https://idp.example.com/token",
        userinfo_url="https://idp.example.com/userinfo",
    )

    with pytest.raises(ConfigValidationError, match="client_secret must be provided"):
        _normalize_provider_payload(
            [
                {
                    "slug": "example",
                    "token_url": "https://other-idp.example.com/token",
                }
            ],
            {"example": existing},
            "merge",
        )


@pytest.mark.anyio
async def test_merge_provider_no_change_is_not_written_or_counted():
    """Normalized endpoint defaults do not turn a preview no-op into an update."""
    from app.platform.config_ops.service import (
        _apply_oauth_providers,
        _normalize_provider_payload,
        _providers_to_apply,
    )

    existing = SimpleNamespace(
        id=uuid.uuid4(),
        slug="example",
        display_name="Example",
        provider_type="oidc",
        client_id="client-id",
        client_secret_encrypted="encrypted-secret",
        discovery_url="https://idp.example.com/.well-known/openid-configuration",
        authorize_url=None,
        token_url=None,
        userinfo_url=None,
        idp_entity_id=None,
        idp_sso_url=None,
        idp_certificate=None,
        sp_entity_id=None,
        scopes="openid profile email",
        default_role="viewer",
        group_claim=None,
        group_role_mapping=None,
        enabled=True,
    )
    normalized, changes = _normalize_provider_payload(
        [{"slug": "example"}],
        {"example": existing},
        "merge",
    )
    providers_to_apply = _providers_to_apply(normalized, changes, "merge")
    db = AsyncMock()

    with (
        patch(
            "app.modules.auth.oauth.service.list_providers",
            AsyncMock(return_value=[existing]),
        ),
        patch(
            "app.modules.auth.oauth.service.update_provider",
            AsyncMock(),
        ) as update_provider,
    ):
        result = await _apply_oauth_providers(db, providers_to_apply, "merge")

    assert changes[0]["action"] == "no_change"
    assert providers_to_apply == []
    assert result == (0, 0, 0, 0)
    update_provider.assert_not_awaited()


@pytest.mark.parametrize("credential_field", ["client_secret", "idp_certificate"])
def test_oauth_preflight_reports_write_only_credential_rotations(
    credential_field: str,
):
    """A credential-only rotation is an update without exposing its value."""
    from app.platform.config_ops.service import _diff_provider

    secret = "never-return-this-secret"
    changed = _diff_provider(
        {"display_name": "Example"},
        {"display_name": "Example", credential_field: secret},
    )

    assert changed == [credential_field]
    assert secret not in repr(changed)


def test_provider_state_binds_write_only_credential_versions():
    """Rotating a stored credential changes overwrite-token state."""
    from app.platform.config_ops.service import _provider_state_dict

    provider_values = {
        "id": uuid.uuid4(),
        "updated_at": datetime.now(timezone.utc),
        "slug": "example",
        "display_name": "Example",
        "provider_type": "oidc",
        "client_id": "client-id",
        "client_secret_encrypted": "encrypted-secret-v1",
        "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
        "authorize_url": None,
        "token_url": None,
        "userinfo_url": None,
        "idp_entity_id": None,
        "idp_sso_url": None,
        "idp_certificate": None,
        "sp_entity_id": None,
        "scopes": "openid profile email",
        "default_role": "viewer",
        "group_claim": None,
        "group_role_mapping": None,
        "enabled": True,
    }
    before = _provider_state_dict(SimpleNamespace(**provider_values))
    provider_values["client_secret_encrypted"] = "encrypted-secret-v2"
    after = _provider_state_dict(SimpleNamespace(**provider_values))

    assert before["client_secret_version"] != after["client_secret_version"]
    assert "encrypted-secret-v1" not in repr(before)
    assert "encrypted-secret-v2" not in repr(after)


def test_preview_digests_are_keyed_and_domain_separated():
    """Payload claims cannot be matched with an offline raw-hash dictionary."""
    from app.platform.config_ops.service import _canonical_digest

    value = {"password_login_enabled": False}
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")

    with patch(
        "app.platform.config_ops.service._preview_signing_key",
        return_value=b"first-preview-key",
    ):
        payload_digest = _canonical_digest(value, domain="payload")
        state_digest = _canonical_digest(value, domain="state")
    with patch(
        "app.platform.config_ops.service._preview_signing_key",
        return_value=b"second-preview-key",
    ):
        other_key_digest = _canonical_digest(value, domain="payload")

    assert payload_digest != hashlib.sha256(raw).hexdigest()
    assert payload_digest != state_digest
    assert payload_digest != other_key_digest


def test_linked_account_state_stales_preview_without_exposing_subject():
    """A link mutation invalidates a token while the subject stays opaque."""
    from app.platform.config_ops.exceptions import ConfigPreviewError
    from app.platform.config_ops.service import (
        ConfigImportPlan,
        _canonical_digest,
        _issue_preview_token,
        _oauth_account_state,
        _verify_preview_token,
    )

    account = SimpleNamespace(
        id=uuid.uuid4(),
        provider_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        subject="do-not-expose-this-subject",
    )
    before = _oauth_account_state(account)
    account.subject = "rotated-do-not-expose-this-subject"
    after = _oauth_account_state(account)

    before_digest = _canonical_digest({"oauth_accounts": [before]}, domain="state")
    after_digest = _canonical_digest({"oauth_accounts": [after]}, domain="state")
    plan = ConfigImportPlan(
        validated_settings={},
        settings_to_apply={},
        normalized_providers=[],
        providers_to_apply=[],
        setting_changes=[],
        provider_changes=[],
        skipped_unknown=[],
        skipped_restricted=[],
        oauth_accounts_deleted=1,
        payload_digest=_canonical_digest({}, domain="payload"),
        state_digest=before_digest,
        caller_is_enterprise=False,
    )
    token = _issue_preview_token(plan, "overwrite")

    assert before_digest != after_digest
    assert "do-not-expose-this-subject" not in repr(before)
    assert "do-not-expose-this-subject" not in token
    with pytest.raises(ConfigPreviewError):
        _verify_preview_token(
            token,
            replace(plan, state_digest=after_digest),
            "overwrite",
        )


def test_overwrite_preview_counts_provider_account_link_deletions():
    """Replace/delete previews report exact link counts, never identities."""
    from app.platform.config_ops.service import _normalize_provider_payload

    provider_id = uuid.uuid4()
    existing = SimpleNamespace(id=provider_id)
    raw = {
        "slug": "example",
        "display_name": "Example",
        "provider_type": "oidc",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "discovery_url": "https://idp.example.com/.well-known/openid-configuration",
    }

    _, replace_changes = _normalize_provider_payload(
        [raw],
        {"example": existing},
        "overwrite",
        {provider_id: 3},
    )
    _, delete_changes = _normalize_provider_payload(
        [],
        {"example": existing},
        "overwrite",
        {provider_id: 3},
    )

    assert replace_changes[0]["action"] == "replace"
    assert replace_changes[0]["dependent_accounts_deleted"] == 3
    assert delete_changes[0]["action"] == "delete"
    assert delete_changes[0]["dependent_accounts_deleted"] == 3


def test_import_login_method_plan_rejects_merge_and_overwrite_lockout():
    """Both modes validate their final provider/password state."""
    from app.platform.config_ops.exceptions import ConfigValidationError
    from app.platform.config_ops.service import _validate_login_method_plan

    existing = [SimpleNamespace(slug="example", enabled=True)]
    with pytest.raises(ConfigValidationError, match="every login method"):
        _validate_login_method_plan(
            password_login_enabled=False,
            existing_providers=existing,
            normalized_providers=[{"slug": "example", "enabled": False}],
            mode="merge",
        )
    with pytest.raises(ConfigValidationError, match="every login method"):
        _validate_login_method_plan(
            password_login_enabled=False,
            existing_providers=existing,
            normalized_providers=[],
            mode="overwrite",
        )


@pytest.mark.parametrize("mode", ["merge", "overwrite"])
def test_import_login_method_plan_accepts_enabled_provider(mode: str):
    """SSO-only plans remain valid when their final state has a provider."""
    from app.platform.config_ops.service import _validate_login_method_plan

    if mode == "merge":
        existing = [SimpleNamespace(slug="example", enabled=True)]
        normalized = []
    else:
        existing = []
        normalized = [{"slug": "example", "enabled": True}]

    _validate_login_method_plan(
        password_login_enabled=False,
        existing_providers=existing,
        normalized_providers=normalized,
        mode=mode,
    )


@pytest.mark.anyio
async def test_overwrite_saml_uses_certificate_not_oauth_client_secret(
    enterprise_edition,
):
    """A validated SAML create is not rejected by the OAuth-secret guard."""
    from app.modules.auth.oauth.schemas import OAuthProviderCreate
    from app.platform.config_ops.service import _apply_oauth_providers

    provider = OAuthProviderCreate(
        slug="enterprise-saml",
        display_name="Enterprise SAML",
        provider_type="saml",
        idp_entity_id="https://idp.example.com/entity",
        idp_sso_url="https://idp.example.com/sso",
        idp_certificate="test-certificate",
        sp_entity_id="https://geolens.example.com/saml/metadata",
    )
    db = AsyncMock()
    db.scalar.return_value = 0
    created_provider = SimpleNamespace(id=uuid.uuid4())

    with (
        patch(
            "app.modules.auth.oauth.service.list_providers",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.modules.auth.oauth.service.create_provider",
            AsyncMock(return_value=created_provider),
        ) as create_provider,
    ):
        result = await _apply_oauth_providers(db, [provider.model_dump()], "overwrite")

    assert result == (1, 0, 0, 0)
    create_provider.assert_awaited_once()


@pytest.mark.anyio
async def test_import_result_and_audit_report_exact_account_link_deletions():
    """The exact cascade count reaches both the response and aggregate audit."""
    from app.platform.config_ops.service import ConfigImportPlan, import_config

    plan = ConfigImportPlan(
        validated_settings={},
        settings_to_apply={},
        normalized_providers=[],
        providers_to_apply=[],
        setting_changes=[],
        provider_changes=[],
        skipped_unknown=[],
        skipped_restricted=[],
        oauth_accounts_deleted=4,
        payload_digest="payload",
        state_digest="state",
        caller_is_enterprise=False,
    )
    db = AsyncMock()

    with (
        patch(
            "app.platform.config_ops.service.acquire_config_import_lock",
            AsyncMock(),
        ),
        patch(
            "app.platform.config_ops.service.preflight_import",
            AsyncMock(return_value=plan),
        ),
        patch("app.platform.config_ops.service._verify_preview_token"),
        patch(
            "app.platform.config_ops.service._apply_oauth_providers",
            AsyncMock(return_value=(0, 0, 0, 4)),
        ),
        patch(
            "app.core.persistent_config.PersistentConfig.reset",
            AsyncMock(),
        ),
        patch(
            "app.core.persistent_config.PersistentConfig.apply_side_effects",
            AsyncMock(),
        ),
        patch("app.modules.audit.service.audit_emit", AsyncMock()) as audit_emit,
    ):
        result = await import_config(
            db,
            {},
            "overwrite",
            uuid.uuid4(),
            None,
            preview_token="preview",
        )

    assert result.oauth_accounts_deleted == 4
    event = audit_emit.await_args.args[1]
    assert event.details["oauth_accounts_deleted"] == 4
    db.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_list_providers_can_load_deferred_saml_export_fields():
    """Config export can request all non-secret SAML fields in one query."""
    from app.modules.auth.oauth.service import list_providers

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    await list_providers(db, include_saml_fields=True)

    statement = str(db.execute.await_args.args[0])
    assert "idp_entity_id" in statement
    assert "idp_sso_url" in statement
    assert "sp_entity_id" in statement

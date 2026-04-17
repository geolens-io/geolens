"""Unit tests for config_ops schemas and service (TDD RED phase)."""


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
    from app.platform.config_ops.service import export_config, import_config, dry_run_import

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

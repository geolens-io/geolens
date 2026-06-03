"""Offline contract tests for manifest CLI commands."""

from __future__ import annotations

import ast
from pathlib import Path

from geolens_cli.main import AppState, app


MANIFEST_PACKAGE = Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest"
MANIFEST_APPLY_MODULE = (
    Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest_apply.py"
)
OFFLINE_FORBIDDEN_IMPORTS = {
    "app",
    "app_enterprise",
    "backend.app",
    "geolens.api",
    "geolens.models",
    "geolens_enterprise",
    "httpx",
    "osgeo",
    "rasterio",
    "requests",
    "sqlalchemy",
}
APPLY_FORBIDDEN_IMPORTS = {
    "app",
    "app_enterprise",
    "backend.app",
    "geolens_enterprise",
    "httpx",
    "osgeo",
    "rasterio",
    "requests",
    "sqlalchemy",
}


def _import_matches_forbidden(module: str, forbidden_imports: set[str]) -> bool:
    return any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for forbidden in forbidden_imports
    )


def _import_offenders(path: Path, forbidden_imports: set[str]) -> list[str]:
    offenders: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = path.read_text(encoding="utf-8").splitlines()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _import_matches_forbidden(alias.name, forbidden_imports):
                    offenders.append(
                        f"{path}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _import_matches_forbidden(node.module, forbidden_imports):
                offenders.append(
                    f"{path}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                )

    return offenders


def test_help_lists_manifest_commands(runner, tmp_xdg_home) -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "init" in result.output
    assert "validate" in result.output


def test_init_then_validate_succeeds_without_sdk(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def explode_sdk(self):
        raise AssertionError("manifest commands must not construct an SDK client")

    monkeypatch.setattr(AppState, "sdk", explode_sdk)

    init_result = runner.invoke(app, ["init"])
    validate_result = runner.invoke(app, ["validate"])

    assert init_result.exit_code == 0, init_result.output
    assert validate_result.exit_code == 0, validate_result.output


def test_manifest_helpers_do_not_import_service_dependencies() -> None:
    offenders: list[str] = []

    for path in sorted(MANIFEST_PACKAGE.glob("*.py")):
        offenders.extend(_import_offenders(path, OFFLINE_FORBIDDEN_IMPORTS))

    assert offenders == []


def test_manifest_apply_does_not_import_backend_or_direct_http_clients() -> None:
    offenders = _import_offenders(MANIFEST_APPLY_MODULE, APPLY_FORBIDDEN_IMPORTS)

    assert offenders == []

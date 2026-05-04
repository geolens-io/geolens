"""Offline contract tests for manifest CLI commands."""

from __future__ import annotations

import ast
from pathlib import Path

from geolens_cli.main import AppState, app


MANIFEST_PACKAGE = Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest"
FORBIDDEN_IMPORTS = {
    "app",
    "backend.app",
    "geolens.api",
    "geolens.models",
    "httpx",
    "osgeo",
    "rasterio",
    "requests",
    "sqlalchemy",
}


def _import_matches_forbidden(module: str) -> bool:
    return any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for forbidden in FORBIDDEN_IMPORTS
    )


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
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _import_matches_forbidden(alias.name):
                        offenders.append(f"{path}:{node.lineno}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if _import_matches_forbidden(node.module):
                    offenders.append(f"{path}:{node.lineno}:{node.module}")

    assert offenders == []

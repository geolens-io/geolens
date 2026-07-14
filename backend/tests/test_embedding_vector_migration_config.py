"""Static/unit coverage for migration 0012 configuration resolution."""

from __future__ import annotations

import ast
import importlib.util
from types import ModuleType

import pytest
import yaml

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_MIGRATION_PATH = _REPO_ROOT / "backend/alembic/versions/0012_type_embedding_vector.py"


@pytest.fixture
def migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_0012_config_test", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_has_no_application_imports() -> None:
    """Topology-only Alembic commands must not initialize app Settings."""
    tree = ast.parse(_MIGRATION_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert not any(name == "app" or name.startswith("app.") for name in imports)


@pytest.mark.parametrize("value", ["768", " 1536 ", "+3072"])
def test_explicit_embedding_dims_accepts_bounded_integers(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
    value: str,
) -> None:
    monkeypatch.setenv("EMBEDDING_DIMS", value)
    assert migration_module._explicit_embedding_dims() == int(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_explicit_embedding_dims_distinguishes_unset(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("EMBEDDING_DIMS", raising=False)
    else:
        monkeypatch.setenv("EMBEDDING_DIMS", value)
    assert migration_module._explicit_embedding_dims() is None


@pytest.mark.parametrize("value", ["zero", "0", "4097"])
def test_explicit_embedding_dims_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
    value: str,
) -> None:
    monkeypatch.setenv("EMBEDDING_DIMS", value)
    with pytest.raises(RuntimeError, match="integer from 1 to 4096"):
        migration_module._explicit_embedding_dims()


@pytest.mark.parametrize("value", ["true", "1", "YES", "on"])
def test_env_only_parser_accepts_true_values(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
    value: str,
) -> None:
    monkeypatch.setenv("ENV_ONLY_CONFIG", value)
    assert migration_module._env_only_config_enabled() is True


@pytest.mark.parametrize("value", [None, "", "false", "0", "NO", "off"])
def test_env_only_parser_accepts_false_values(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("ENV_ONLY_CONFIG", raising=False)
    else:
        monkeypatch.setenv("ENV_ONLY_CONFIG", value)
    assert migration_module._env_only_config_enabled() is False


def test_env_only_parser_rejects_ambiguous_values(
    monkeypatch: pytest.MonkeyPatch,
    migration_module: ModuleType,
) -> None:
    monkeypatch.setenv("ENV_ONLY_CONFIG", "sometimes")
    with pytest.raises(RuntimeError, match="must be one of"):
        migration_module._env_only_config_enabled()


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_migrate_service_receives_embedding_config(filename: str) -> None:
    body = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
    environment = body["services"]["migrate"]["environment"]
    assert environment["EMBEDDING_DIMS"] == "${EMBEDDING_DIMS-}"
    assert environment["ENV_ONLY_CONFIG"] == "${ENV_ONLY_CONFIG:-false}"


def test_vector_transition_is_bounded_and_concurrent() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    lock_timeout = source.index("set_config('lock_timeout', '5s', true)")
    truncate = source.index("TRUNCATE catalog.record_embeddings")
    assert lock_timeout < truncate
    assert "TRUNCATE catalog.record_embeddings" in source
    assert "DELETE FROM catalog.record_embeddings" not in source
    assert "autocommit_block()" in source
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in source


def test_concurrent_index_recovery_rejects_invalid_same_name_index() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    validity_check = source.index("idx.indisvalid AND idx.indisready")
    invalid_drop = source.index("DROP INDEX CONCURRENTLY IF EXISTS")
    concurrent_create = source.index("CREATE INDEX CONCURRENTLY IF NOT EXISTS")
    assert validity_check < invalid_drop < concurrent_create

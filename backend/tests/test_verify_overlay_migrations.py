"""No-database self-tests for the install-agnostic overlay verifier."""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.verify_overlay_migrations as verifier_module
from scripts.verify_overlay_migrations import (
    DatabaseState,
    MigrationTopology,
    OverlayMigrationVerificationError,
    SAML_COLUMNS,
    discover_overlay_migration_paths,
    read_database_state,
    resolve_migration_topology,
    validate_database_state,
)


class _FakeEntryPoint:
    def __init__(self, name: str, provider=None, error: Exception | None = None):
        self.name = name
        self._provider = provider
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._provider


def test_discovery_requires_a_real_installed_entry_point() -> None:
    with pytest.raises(
        OverlayMigrationVerificationError, match="no geolens.migrations"
    ):
        discover_overlay_migration_paths([])


def test_discovery_validates_and_deduplicates_provider_paths(tmp_path: Path) -> None:
    versions = tmp_path / "overlay" / "versions"
    versions.mkdir(parents=True)
    entry_point = _FakeEntryPoint(
        "fixture-overlay", lambda: [str(versions), str(versions)]
    )

    assert discover_overlay_migration_paths([entry_point]) == (versions.resolve(),)


def test_discovery_surfaces_broken_installed_overlay() -> None:
    entry_point = _FakeEntryPoint(
        "broken-overlay", error=ImportError("missing overlay submodule")
    )
    with pytest.raises(
        OverlayMigrationVerificationError, match="broken-overlay.*missing overlay"
    ):
        discover_overlay_migration_paths([entry_point])


def test_topology_resolves_core_and_fixture_overlay_heads(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "fixture_overlay_head.py").write_text(
        "\n".join(
            (
                'revision = "fixture_overlay_head"',
                'down_revision = "0002_procrastinate"',
                'branch_labels = ("fixture_overlay",)',
                "depends_on = None",
                "def upgrade(): pass",
                "def downgrade(): pass",
            )
        )
    )

    topology = resolve_migration_topology(backend_dir, [versions])

    assert len(topology.core_heads) == 1
    assert topology.overlay_heads == ("fixture_overlay_head",)


def _valid_state() -> tuple[MigrationTopology, DatabaseState]:
    topology = MigrationTopology(
        core_heads=("core_head",),
        overlay_heads=("fixture_overlay_head",),
    )
    state = DatabaseState(
        applied_heads=topology.all_heads,
        saml_columns=SAML_COLUMNS,
        provider_constraint=(
            "CHECK (provider_type IN ('oidc', 'google', 'microsoft', 'saml', 'github'))"
        ),
    )
    return topology, state


def test_database_contract_accepts_converged_heads_and_provider_union() -> None:
    topology, state = _valid_state()
    validate_database_state(topology, state)


def test_database_contract_rejects_a_dropped_overlay_provider_type() -> None:
    topology, state = _valid_state()
    broken = DatabaseState(
        applied_heads=state.applied_heads,
        saml_columns=state.saml_columns,
        provider_constraint=(
            "CHECK (provider_type IN ('oidc', 'google', 'microsoft', 'saml'))"
        ),
    )

    with pytest.raises(OverlayMigrationVerificationError, match="github"):
        validate_database_state(topology, broken)


def test_database_contract_rejects_a_vacuously_missing_overlay_head() -> None:
    topology, state = _valid_state()
    broken = DatabaseState(
        applied_heads=topology.core_heads,
        saml_columns=state.saml_columns,
        provider_constraint=state.provider_constraint,
    )

    with pytest.raises(
        OverlayMigrationVerificationError, match="applied Alembic heads"
    ):
        validate_database_state(topology, broken)


async def test_database_state_reader_is_side_effect_free(monkeypatch) -> None:
    topology, expected = _valid_state()

    class _Result:
        def __init__(self, *, scalars=(), scalar=None):
            self._scalars = scalars
            self._scalar = scalar

        def scalars(self):
            return iter(self._scalars)

        def scalar_one_or_none(self):
            return self._scalar

    results = iter(
        (
            _Result(scalars=topology.all_heads),
            _Result(scalars=SAML_COLUMNS),
            _Result(scalar=expected.provider_constraint),
        )
    )

    class _Connection:
        async def execute(self, _statement, _params=None):
            return next(results)

    class _ConnectionContext:
        async def __aenter__(self):
            return _Connection()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

    class _Engine:
        disposed = False

        def connect(self):
            return _ConnectionContext()

        async def dispose(self):
            self.disposed = True

    engine = _Engine()
    monkeypatch.setattr(
        verifier_module, "create_async_engine", lambda *_args, **_kwargs: engine
    )

    assert await read_database_state() == expected
    assert engine.disposed is True

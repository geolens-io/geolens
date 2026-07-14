"""Verify an installed migration overlay against the current core chain.

The verifier is deliberately overlay-agnostic: it discovers providers through
the public ``geolens.migrations`` entry-point contract and never imports a
private package by name. It is intended for an overlay-owned CI job (or a
locally built enterprise image) where the real overlay is already installed.

It fails rather than skips when no overlay is present, upgrades every Alembic
head through the production environment, checks that every discovered head was
recorded, validates the co-owned OAuth/SAML schema, and runs Alembic's drift
check. Public core CI does not fetch private source to run this command.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from importlib import metadata
import os
from pathlib import Path
import sys
from typing import Iterable

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


MIGRATION_ENTRY_POINT_GROUP = "geolens.migrations"
SAML_COLUMNS = frozenset(
    {"idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id"}
)
SUPPORTED_PROVIDER_TYPES = frozenset({"oidc", "google", "microsoft", "saml", "github"})
DEFAULT_BACKEND_DIR = Path(__file__).resolve().parents[1]


class OverlayMigrationVerificationError(RuntimeError):
    """Raised when the installed overlay fails a migration contract."""


@dataclass(frozen=True)
class MigrationTopology:
    core_heads: tuple[str, ...]
    overlay_heads: tuple[str, ...]

    @property
    def all_heads(self) -> tuple[str, ...]:
        return tuple(sorted((*self.core_heads, *self.overlay_heads)))


@dataclass(frozen=True)
class DatabaseState:
    applied_heads: tuple[str, ...]
    saml_columns: frozenset[str]
    provider_constraint: str | None


def discover_overlay_migration_paths(
    entry_points: Iterable[object] | None = None,
) -> tuple[Path, ...]:
    """Load and validate every installed migration path provider."""
    providers = list(
        entry_points
        if entry_points is not None
        else metadata.entry_points(group=MIGRATION_ENTRY_POINT_GROUP)
    )
    if not providers:
        raise OverlayMigrationVerificationError(
            "no geolens.migrations entry point is installed; this verifier must "
            "run in an image or environment containing the real overlay"
        )

    paths: list[Path] = []
    for entry_point in providers:
        name = str(getattr(entry_point, "name", entry_point))
        try:
            provider = entry_point.load()
        except Exception as exc:
            raise OverlayMigrationVerificationError(
                f"failed to load migration entry point {name!r}: {exc}"
            ) from exc
        if not callable(provider):
            raise OverlayMigrationVerificationError(
                f"migration entry point {name!r} did not resolve to a callable"
            )

        try:
            provided = provider()
        except Exception as exc:
            raise OverlayMigrationVerificationError(
                f"migration path provider {name!r} failed: {exc}"
            ) from exc
        if isinstance(provided, (str, os.PathLike)):
            provided_values = [provided]
        else:
            try:
                provided_values = list(provided)
            except TypeError as exc:
                raise OverlayMigrationVerificationError(
                    f"migration path provider {name!r} did not return an iterable"
                ) from exc

        provider_paths = [Path(value).resolve() for value in provided_values]
        if not provider_paths:
            raise OverlayMigrationVerificationError(
                f"migration path provider {name!r} returned no paths"
            )
        missing = [path for path in provider_paths if not path.is_dir()]
        if missing:
            raise OverlayMigrationVerificationError(
                f"migration path provider {name!r} returned missing directories: "
                + ", ".join(str(path) for path in missing)
            )
        paths.extend(provider_paths)

    # Preserve provider order while removing duplicate directories.
    return tuple(dict.fromkeys(paths))


def resolve_migration_topology(
    backend_dir: Path,
    overlay_paths: Iterable[Path],
) -> MigrationTopology:
    """Resolve core and overlay heads without running the Alembic environment."""
    backend_dir = backend_dir.resolve()
    core_versions = (backend_dir / "alembic" / "versions").resolve()
    overlay_roots = tuple(path.resolve() for path in overlay_paths)

    config = _alembic_config(backend_dir)
    config.set_main_option("path_separator", "os")
    config.set_main_option(
        "version_locations",
        os.pathsep.join(str(path) for path in (core_versions, *overlay_roots)),
    )
    scripts = ScriptDirectory.from_config(config)

    core_heads: list[str] = []
    overlay_heads: list[str] = []
    for head in scripts.get_heads():
        revision = scripts.get_revision(head)
        if revision is None or revision.path is None:
            raise OverlayMigrationVerificationError(
                f"could not resolve source path for Alembic head {head!r}"
            )
        revision_path = Path(revision.path).resolve()
        if revision_path.is_relative_to(core_versions):
            core_heads.append(head)
        elif any(revision_path.is_relative_to(root) for root in overlay_roots):
            overlay_heads.append(head)
        else:
            raise OverlayMigrationVerificationError(
                f"Alembic head {head!r} came from an unexpected path: {revision_path}"
            )

    if not core_heads:
        raise OverlayMigrationVerificationError("the core migration head is missing")
    if not overlay_heads:
        raise OverlayMigrationVerificationError(
            "no overlay migration head was resolved from the installed providers"
        )
    return MigrationTopology(tuple(sorted(core_heads)), tuple(sorted(overlay_heads)))


def _alembic_config(backend_dir: Path) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return config


def upgrade_all_heads(backend_dir: Path) -> None:
    """Exercise the production entry-point discovery path and migrate all heads."""
    command.upgrade(_alembic_config(backend_dir), "heads")


def check_model_drift(backend_dir: Path) -> None:
    command.check(_alembic_config(backend_dir))


async def read_database_state() -> DatabaseState:
    """Read the post-migration contract from the configured database."""
    from app.core.config import settings

    engine = create_async_engine(
        settings.database_url,
        connect_args=settings.database_connect_args,
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            heads_result = await connection.execute(
                text(
                    "SELECT version_num FROM catalog.alembic_version "
                    "ORDER BY version_num"
                )
            )
            heads = tuple(heads_result.scalars())
            columns_result = await connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'catalog'
                      AND table_name = 'oauth_providers'
                      AND column_name = ANY(CAST(:column_names AS text[]))
                    """
                ),
                {"column_names": sorted(SAML_COLUMNS)},
            )
            columns = frozenset(columns_result.scalars())
            constraint = (
                await connection.execute(
                    text(
                        """
                        SELECT pg_get_constraintdef(constraint_row.oid)
                        FROM pg_catalog.pg_constraint AS constraint_row
                        WHERE constraint_row.conname = 'chk_oauth_providers_type'
                          AND constraint_row.conrelid =
                              'catalog.oauth_providers'::regclass
                        """
                    )
                )
            ).scalar_one_or_none()
            return DatabaseState(
                applied_heads=heads,
                saml_columns=columns,
                provider_constraint=constraint,
            )
    finally:
        await engine.dispose()


def validate_database_state(
    topology: MigrationTopology,
    state: DatabaseState,
) -> None:
    expected_heads = set(topology.all_heads)
    applied_heads = set(state.applied_heads)
    if applied_heads != expected_heads:
        raise OverlayMigrationVerificationError(
            "applied Alembic heads do not match discovered heads: "
            f"expected={sorted(expected_heads)}, applied={sorted(applied_heads)}"
        )

    missing_columns = SAML_COLUMNS - state.saml_columns
    if missing_columns:
        raise OverlayMigrationVerificationError(
            "oauth_providers is missing overlay-compatible SAML columns: "
            + ", ".join(sorted(missing_columns))
        )

    if state.provider_constraint is None:
        raise OverlayMigrationVerificationError(
            "chk_oauth_providers_type is missing from catalog.oauth_providers"
        )
    missing_types = {
        provider_type
        for provider_type in SUPPORTED_PROVIDER_TYPES
        if f"'{provider_type}'" not in state.provider_constraint
    }
    if missing_types:
        raise OverlayMigrationVerificationError(
            "chk_oauth_providers_type omits supported provider types: "
            + ", ".join(sorted(missing_types))
        )


def verify_overlay_migrations(backend_dir: Path = DEFAULT_BACKEND_DIR) -> None:
    """Run the complete installed-overlay migration compatibility contract."""
    backend_dir = backend_dir.resolve()
    overlay_paths = discover_overlay_migration_paths()
    topology = resolve_migration_topology(backend_dir, overlay_paths)

    print("Discovered overlay migration paths:")
    for path in overlay_paths:
        print(f"  - {path}")
    print(f"Core heads:    {', '.join(topology.core_heads)}")
    print(f"Overlay heads: {', '.join(topology.overlay_heads)}")

    upgrade_all_heads(backend_dir)
    state = asyncio.run(read_database_state())
    validate_database_state(topology, state)
    check_model_drift(backend_dir)

    print(
        "Overlay migration verification passed: all heads applied, OAuth/SAML "
        "schema converged, and Alembic reported no model drift."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-dir",
        type=Path,
        default=DEFAULT_BACKEND_DIR,
        help="GeoLens backend directory containing alembic.ini (default: inferred)",
    )
    args = parser.parse_args(argv)

    try:
        verify_overlay_migrations(args.backend_dir)
    except Exception as exc:
        print(f"Overlay migration verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Phase 275 / API-05 + API-08 + API-10 regression: compose alignment locks.

Pinned by Phase 275 Plan 06. These tests enforce three invariants that the
inline comments in docker-compose.yml + Dockerfile
encode but cannot self-verify:

1. The compose-vs-.env.example dual-default for DB_PORT / API_PORT is
   intentional and documented.
2. The titiler / valkey image pins are not stuck at their original (M-25
   era) tags.
3. The uv installer pin is byte-aligned across every Dockerfile stage.
4. Deferred commercial-overlay material is not documented in the public
   repository surfaces.
"""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)


def _read(path: str) -> str:
    return (_REPO_ROOT / path).read_text(encoding="utf-8")


def _exists(path: str) -> bool:
    return (_REPO_ROOT / path).exists()


def test_compose_dual_default_documented() -> None:
    """API-05 / M-25: docker-compose.yml port fallbacks differ from .env.example by design."""
    body = _read("docker-compose.yml")
    # NOTE: the original ">=2 'API-05 (Phase 275)' inline-comment" assertion was
    # dropped after commit fec874a6 ("docs(compose): replace long Phase-ID
    # archaeology with one-line pointers") intentionally removed per-line phase
    # citations from docker-compose.yml. The load-bearing invariant is the
    # functional fallback below (no-.env baseline still binds 5432 / 8000), not
    # the comment archaeology.
    # The fallback values themselves must remain unchanged so `docker compose up`
    # without copying .env still binds to 5432 / 8000.
    assert "${DB_PORT:-5432}:5432" in body, (
        "DB_PORT fallback must remain :-5432 (no-.env baseline) per Phase 275 decision"
    )
    assert "${API_PORT:-8000}:8000" in body, (
        "API_PORT fallback must remain :-8000 (no-.env baseline) per Phase 275 decision"
    )


def test_titiler_image_pinned() -> None:
    """API-08 / L-19: titiler must NOT be pinned at 2.0.0 (the floor of the 2.x line)."""
    body = _read("docker-compose.yml")
    assert "ghcr.io/developmentseed/titiler:2.0.0" not in body, (
        "titiler is still pinned at 2.0.0 — bump to a current 2.x tag (L-19)"
    )
    # Sanity-check that some titiler 2.x pin exists.
    match = re.search(r"ghcr\.io/developmentseed/titiler:(\d+)\.(\d+)\.(\d+)", body)
    assert match, "titiler image pin missing"
    major, minor, patch = (int(g) for g in match.groups())
    assert major == 2, (
        f"titiler major version is {major}; should remain 2 until contract testing "
        "of the GeoLens-consumed /cog/* + /healthz surface"
    )
    # Allow any 2.x with at least one of (minor, patch) > 0 — moves forward from 2.0.0.
    assert minor > 0 or patch > 0, "titiler pin must move forward from 2.0.0"


def test_valkey_image_pinned() -> None:
    """API-08 / L-20: valkey must NOT be pinned at 8.1.6-alpine."""
    body = _read("docker-compose.yml")
    assert "valkey/valkey:8.1.6-alpine" not in body, (
        "valkey is still pinned at 8.1.6-alpine — bump (L-20)"
    )
    match = re.search(r"valkey/valkey:(\d+)\.(\d+)\.(\d+)-alpine", body)
    assert match, "valkey 8.x-alpine image pin missing"
    major = int(match.group(1))
    assert major == 8, f"valkey major version is {major}; should remain 8"


def test_uv_installer_pins_are_aligned() -> None:
    """API-08 / L-21: all numeric uv installer pins must agree on a single version.

    Only matches numeric `vMAJOR.MINOR.PATCH`-style pins. `python3.x-bookworm-slim`
    convenience tags are a different pin namespace and are out of scope.
    """
    versions: set[str] = set()
    for filename in ("docker-compose.yml", "Dockerfile"):
        path = _REPO_ROOT / filename
        if not path.exists():
            continue
        for match in re.finditer(
            r"astral-sh/uv:(\d+\.\d+\.\d+)", path.read_text(encoding="utf-8")
        ):
            versions.add(match.group(1))
    if versions:
        assert len(versions) == 1, (
            f"uv installer pins disagree across files: {sorted(versions)} — "
            "align to a single version"
        )


def test_deferred_overlay_not_documented_in_public_surfaces() -> None:
    """API-10 / M-53: the private Enterprise *implementation* must not leak into
    public surfaces.

    The open-core Editions boundary itself (Community vs. Enterprise) IS
    intentionally documented publicly in EDITIONS.md and the README Editions
    section (v1048 REL-01) — open-core transparency is the goal, so naming the
    "Enterprise" edition in the README is expected. What must stay private is the
    enterprise *implementation*: the overlay compose file and the private
    repo/image name. `.env.example` is a config template and stays free of
    edition material.
    """
    readme = _read("README.md")
    env_example = _read(".env.example")

    assert not _exists("docker-compose.enterprise.yml"), (
        "docker-compose.enterprise.yml should not be in the public repo root"
    )
    for body in (readme, env_example):
        assert "docker-compose.enterprise.yml" not in body
        assert "geolens-enterprise" not in body
    # README documents the Editions boundary (REL-01); .env.example must not.
    assert "Enterprise" not in env_example

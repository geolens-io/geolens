"""Phase 275 / API-05 + API-08 + API-10 regression: compose alignment locks.

Pinned by Phase 275 Plan 06. These tests enforce three invariants that the
inline comments in docker-compose.yml + Dockerfile + .claude/commands/oc-audit.md
encode but cannot self-verify:

1. The compose-vs-.env.example dual-default for DB_PORT / API_PORT is
   intentional and documented.
2. The titiler / valkey image pins are not stuck at their original (M-25
   era) tags.
3. The uv installer pin is byte-aligned across every Dockerfile stage.
4. The oc-audit methodology no longer claims docker-compose.enterprise.yml
   "exists alongside" the OSS compose files — it lives in the private
   geolens-enterprise overlay.
"""

from __future__ import annotations

import re
from pathlib import Path

# Test runs with pytest cwd=`backend/` (per Makefile + planner contract); the
# files this regression locks live at the repo root. Derive the repo root from
# this file's location so the test is robust regardless of pytest cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(path: str) -> str:
    return (_REPO_ROOT / path).read_text(encoding="utf-8")


def _exists(path: str) -> bool:
    return (_REPO_ROOT / path).exists()


def test_compose_dual_default_documented() -> None:
    """API-05 / M-25: docker-compose.yml port fallbacks differ from .env.example by design."""
    body = _read("docker-compose.yml")
    # The dual-default rationale must be explicit at both DB and API port sites.
    count = body.count("API-05 (Phase 275)")
    assert count >= 2, (
        "docker-compose.yml must document the dual-default for DB_PORT and API_PORT "
        f"(API-05): expected >=2 'API-05 (Phase 275)' comments, got {count}"
    )
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


def test_oc_audit_methodology_acknowledges_enterprise_repo() -> None:
    """API-10 / M-53: oc-audit references the enterprise repo for docker-compose.enterprise.yml."""
    body = _read(".claude/commands/oc-audit.md")
    # The OSS repo must NOT carry the file.
    assert not _exists("docker-compose.enterprise.yml"), (
        "docker-compose.enterprise.yml should NOT be in the OSS repo root — it "
        "lives in the private geolens-enterprise overlay"
    )
    # The misleading "# known to exist" comment in Subagent 4 step 1 must be gone.
    assert "# known to exist" not in body, (
        ".claude/commands/oc-audit.md Subagent 4 step 1 still has the "
        "'# known to exist' comment for docker-compose.enterprise.yml. Update "
        "the cat command to point at the enterprise repo path (API-10 / M-53)."
    )
    # The corrected reference to the enterprise repo must be present.
    assert "~/Code/geolens-enterprise" in body, (
        ".claude/commands/oc-audit.md must reference the local enterprise overlay "
        "path '~/Code/geolens-enterprise' so the audit methodology points at where "
        "docker-compose.enterprise.yml actually lives (API-10 / M-53)."
    )

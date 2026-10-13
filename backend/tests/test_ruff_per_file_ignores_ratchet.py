"""Ruff ``per-file-ignores`` in ``backend/pyproject.toml`` may only shrink.

``extend-per-file-ignores`` counts toward the same baseline, and extending
another ruff config, or adding another one under ``backend/``, is rejected
because its ignores would go unchecked.

The config must match ``_BASELINE`` exactly: adding a glob or a rule code fails
the test, and so does removing one without deleting it from the baseline.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_PYPROJECT = _BACKEND / "pyproject.toml"
_SKIP_DIRS = {"node_modules", "__pycache__"}

_BASELINE: dict[str, frozenset[str]] = {
    path: frozenset({"C901"})
    for path in (
        "app/modules/auth/oauth/service.py",
        "app/modules/catalog/maps/filter_grammar.py",
        "app/modules/catalog/maps/service_diff.py",
        "app/modules/catalog/maps/sprites.py",
        "app/modules/catalog/maps/style_json.py",
        "app/modules/catalog/search/router.py",
        "app/modules/catalog/search/service_records.py",
        "app/modules/catalog/sources/router.py",
        "app/modules/embed_tokens/service.py",
        "app/platform/extensions/defaults_ai_openai.py",
        "app/processing/ai/chat_actions.py",
        "app/processing/ai/metadata_service.py",
        "app/processing/ai/streaming.py",
        "app/processing/export/router.py",
        "app/processing/ingest/tasks_raster.py",
        "app/processing/ingest/tasks_vector.py",
        "app/processing/ingest/tasks_vrt.py",
        "app/processing/raster/quicklook.py",
        "app/processing/tiles/router.py",
        "app/standards/dcat/service.py",
        "app/standards/dcat_us/service.py",
        "app/standards/geodcat_ap/service.py",
        "app/standards/ogc/router.py",
        "app/standards/stac/router.py",
    )
}


def _configured() -> dict[str, frozenset[str]]:
    with _PYPROJECT.open("rb") as f:
        ruff = tomllib.load(f)["tool"]["ruff"]
    assert "extend" not in ruff, (
        "backend/pyproject.toml extends another ruff config, whose per-file-ignores "
        "this ratchet cannot see."
    )
    lint = ruff["lint"]
    merged: dict[str, frozenset[str]] = {}
    for table in ("per-file-ignores", "extend-per-file-ignores"):
        for glob, codes in lint.get(table, {}).items():
            merged[glob] = merged.get(glob, frozenset()) | frozenset(codes)
    return merged


def test_per_file_ignores_never_grow() -> None:
    configured = _configured()
    added = sorted(
        f"{glob}: {code}"
        for glob, codes in configured.items()
        for code in codes - _BASELINE.get(glob, frozenset())
    )
    assert not added, (
        "New ruff per-file-ignores in backend/pyproject.toml: "
        f"{added}. Fix the code instead of widening the ignore."
    )


def test_per_file_ignores_baseline_is_exact() -> None:
    configured = _configured()
    stale = sorted(
        f"{glob}: {code}"
        for glob, codes in _BASELINE.items()
        for code in codes - configured.get(glob, frozenset())
    )
    assert not stale, (
        "These per-file-ignores are gone from backend/pyproject.toml but still "
        f"in _BASELINE: {stale}. Delete them from _BASELINE so the ratchet moves down."
    )


def _other_ruff_configs() -> list[str]:
    found = []
    for root, dirs, files in os.walk(_BACKEND):
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d not in _SKIP_DIRS
            and Path(root, d) != _BACKEND / "staging"
        ]
        for name in files:
            path = Path(root) / name
            if path == _PYPROJECT:
                continue
            if name in ("ruff.toml", ".ruff.toml"):
                found.append(str(path.relative_to(_BACKEND)))
            elif name == "pyproject.toml":
                with path.open("rb") as f:
                    if "ruff" in tomllib.load(f).get("tool", {}):
                        found.append(str(path.relative_to(_BACKEND)))
    return found


def test_no_other_ruff_config_under_backend() -> None:
    others = _other_ruff_configs()
    assert not others, (
        f"Ruff configs {others} can override backend/pyproject.toml "
        "and escape the per-file-ignores ratchet."
    )

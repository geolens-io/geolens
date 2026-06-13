"""Static-analysis test: the frontend LEGACY_BUILDER_PAINT_KEYS Set must be
a strict subset of the backend LEGACY_BUILDER_PAINT_KEYS dict.

Contract (GUARD-01):
  The frontend set (`frontend/src/lib/normalize-style-config.ts`) lists the
  `_`-prefixed (and a handful of unprefixed) paint keys that
  `stripLegacyBuilderPaint` removes from the MapLibre paint object before a
  layer is saved. The backend dict (`schemas.py:LEGACY_BUILDER_PAINT_KEYS`) is
  the authoritative map from those same keys to their `style_config.builder`
  storage fields. The backend moves every key it recognises out of paint during
  import; any key the frontend strips but the backend does not recognise would
  be silently dropped — the v1034 footgun.

  The safe direction is frontend ⊆ backend: every key the frontend strips must
  be handled by the backend. The backend may contain additional keys (e.g. the
  raster-builder keys `_colormap`, `_stretch`, `_pmin`, `_pmax`, `_sigma`)
  that the frontend intentionally keeps in the in-memory paint view and does
  NOT strip via this Set. Those extra backend keys are not a bug.

  A second assertion guards the single-source-of-truth import: style_json.py
  must import LEGACY_BUILDER_PAINT_KEYS from schemas rather than redefining it.

  Fail-before is provable: temporarily add a fake key (e.g. '_zzz-fake') to
  the frontend Set literal — the subset assertion fails and names the offending
  key. Removing it → GREEN.
"""

from __future__ import annotations

import re

from app.modules.catalog.maps.schemas import LEGACY_BUILDER_PAINT_KEYS
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
NORMALIZE_STYLE_CONFIG_TS = (
    REPO_ROOT / "frontend" / "src" / "lib" / "normalize-style-config.ts"
)
STYLE_JSON_PY = (
    REPO_ROOT / "backend" / "app" / "modules" / "catalog" / "maps" / "style_json.py"
)


def _parse_frontend_paint_keys() -> set[str]:
    """Parse the LEGACY_BUILDER_PAINT_KEYS Set literal from the TypeScript source.

    Matches the body between ``new Set([`` and ``])`` on the declaration line
    for ``const LEGACY_BUILDER_PAINT_KEYS``, then extracts every quoted string
    literal (single or double quote) as a key.

    Static analysis only — does not import or execute TypeScript.
    """
    source = NORMALIZE_STYLE_CONFIG_TS.read_text(encoding="utf-8")
    match = re.search(
        r"const\s+LEGACY_BUILDER_PAINT_KEYS\s*=\s*new\s+Set\(\[(.*?)\]\)",
        source,
        re.DOTALL,
    )
    assert match, (
        f"Could not find `const LEGACY_BUILDER_PAINT_KEYS = new Set([...])` in "
        f"{NORMALIZE_STYLE_CONFIG_TS}. The drift guard cannot run without it. "
        f"If the constant was renamed or moved, update this test accordingly."
    )
    body = match.group(1)
    keys = re.findall(r"""['"]([^'"]+)['"]""", body)
    assert keys, (
        f"Regex matched the Set body in {NORMALIZE_STYLE_CONFIG_TS} but found "
        f"no quoted string literals inside it. The parser may be broken."
    )
    return set(keys)


def test_paint_key_allowlist_parity():
    """Frontend LEGACY_BUILDER_PAINT_KEYS must be a subset of backend dict keys.

    Contract direction (GUARD-01):
      frontend_set ⊆ backend_dict_keys

    Every key the frontend strips from paint must be recognised by the backend.
    Divergence here causes silent data loss on map save (the v1034 footgun).

    Known intentional asymmetry: the backend dict includes raster-builder-private
    keys (_colormap, _stretch, _pmin, _pmax, _sigma) that the frontend keeps in
    the in-memory paint view (re-injected by normalizeLayerStyleState after load)
    and does NOT strip via this Set. Those extra backend keys are correct design.
    """
    frontend_keys = _parse_frontend_paint_keys()
    backend_keys = set(LEGACY_BUILDER_PAINT_KEYS.keys())

    only_in_frontend = frontend_keys - backend_keys

    assert not only_in_frontend, (
        f"GUARD-01 DRIFT: frontend LEGACY_BUILDER_PAINT_KEYS contains keys that "
        f"the backend dict does not recognise.\n"
        f"\n"
        f"Keys only in frontend (will be silently dropped on map save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: add the missing keys to LEGACY_BUILDER_PAINT_KEYS in\n"
        f"  backend/app/modules/catalog/maps/schemas.py\n"
        f"or remove them from the frontend Set in\n"
        f"  frontend/src/lib/normalize-style-config.ts\n"
        f"Both files must stay in sync for the keys the frontend strips."
    )

    # Informational: log the known backend-only keys for reviewers.
    only_in_backend = backend_keys - frontend_keys
    if only_in_backend:
        # These are intentional (e.g. raster keys the frontend re-injects into
        # in-memory paint rather than stripping). No assertion failure here.
        pass  # documented in GUARD-01 SUMMARY


def test_style_json_imports_not_redefines_paint_keys():
    """style_json.py must import LEGACY_BUILDER_PAINT_KEYS from schemas, not redefine it.

    The single source of truth for paint-key→storage-field mapping is
    ``backend/app/modules/catalog/maps/schemas.py``. A second definition
    in ``style_json.py`` would silently diverge from the source of truth.

    This test guards the import contract: the constant must be imported,
    and the file must NOT contain a standalone assignment
    ``LEGACY_BUILDER_PAINT_KEYS = ...``.
    """
    source = STYLE_JSON_PY.read_text(encoding="utf-8")

    # Must import the constant from schemas
    assert (
        "LEGACY_BUILDER_PAINT_KEYS" in source
        and "from app.modules.catalog.maps.schemas import" in source
    ), (
        f"style_json.py no longer imports LEGACY_BUILDER_PAINT_KEYS from schemas. "
        f"Check {STYLE_JSON_PY} — the import must be preserved so there is a "
        f"single source of truth for the paint-key allowlist."
    )

    # Must NOT redefine the constant (a bare assignment is a second definition)
    redefinition = re.search(
        r"^LEGACY_BUILDER_PAINT_KEYS\s*=",
        source,
        re.MULTILINE,
    )
    assert not redefinition, (
        f"GUARD-01: style_json.py redefines LEGACY_BUILDER_PAINT_KEYS at line "
        f"{source[: redefinition.start()].count(chr(10)) + 1}. "
        f"Remove this redefinition — the constant must only live in schemas.py."
    )

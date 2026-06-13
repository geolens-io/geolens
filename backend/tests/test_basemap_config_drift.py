"""Static-analysis test: the frontend normalizeBasemapConfig preserve-set must
be a subset of the backend BasemapConfig allowed fields.

Contract (GUARD-02):
  `normalizeBasemapConfig` in `frontend/src/lib/basemap-utils.ts` builds a
  `normalized` object whose keys are sent to the backend as
  `basemap_config` on map save. `BasemapConfig` is declared with
  `model_config = ConfigDict(extra="forbid")` — any key the frontend sends
  that the backend model does not declare causes a silent 422 (the
  basemap_config additive-fields footgun documented in MEMORY.md).

  The safe direction is frontend_preserve_set ⊆ backend_fields: every field
  the frontend writes onto `normalized` must be declared by `BasemapConfig`.
  The backend may declare additional optional fields that the frontend never
  writes; that is not a bug.

  A second assertion guards the `extra='forbid'` configuration itself: if it
  is ever weakened to `extra='ignore'` or removed, this guard's safety premise
  becomes untestable, so the test fails to surface the regression.

  Fail-before is provable: temporarily add `normalized.fake_field = 'x';`
  inside normalizeBasemapConfig → the subset assertion fails naming `fake_field`.
  Removing it → GREEN.
"""

from __future__ import annotations

import re

from app.modules.catalog.maps.schemas import BasemapConfig
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
BASEMAP_UTILS_TS = REPO_ROOT / "frontend" / "src" / "lib" / "basemap-utils.ts"


def _parse_frontend_basemap_preserve_set() -> set[str]:
    """Parse field names assigned onto `normalized` inside normalizeBasemapConfig.

    Strategy:
    1. Locate the body of `export function normalizeBasemapConfig(` up to the
       closing `return normalized;` statement.
    2. Extract object-literal keys from the `const normalized: MapBasemapConfig = { ... }`
       initialiser (identifier keys before `:` in a TS object literal).
    3. Extract every `normalized.<identifier> =` assignment outside the literal
       (the conditional basemap_position / projection / sublayer_overrides lines).

    Static analysis only — does not import or execute TypeScript.
    """
    source = BASEMAP_UTILS_TS.read_text(encoding="utf-8")

    # Step 1: isolate the function body
    func_match = re.search(
        r"export\s+function\s+normalizeBasemapConfig\s*\(",
        source,
    )
    assert func_match, (
        f"Could not find `export function normalizeBasemapConfig(` in "
        f"{BASEMAP_UTILS_TS}. If the function was renamed or moved, "
        f"update this test accordingly."
    )
    func_start = func_match.start()
    # Find `return normalized;` after the function start
    return_match = re.search(r"\breturn\s+normalized\s*;", source[func_start:])
    assert return_match, (
        f"Could not find `return normalized;` inside normalizeBasemapConfig in "
        f"{BASEMAP_UTILS_TS}. The parser may be broken."
    )
    func_body = source[func_start : func_start + return_match.end()]

    # Step 2: object-literal keys in `const normalized: ... = { ... }`
    literal_match = re.search(
        r"const\s+normalized\s*:\s*\w+\s*=\s*\{(.*?)\}",
        func_body,
        re.DOTALL,
    )
    assert literal_match, (
        f"Could not find `const normalized: ... = {{ ... }}` inside "
        f"normalizeBasemapConfig in {BASEMAP_UTILS_TS}. The parser may be broken."
    )
    literal_body = literal_match.group(1)
    # Match `identifier_key:` — TS object keys that are valid Python snake_case identifiers
    literal_keys = set(re.findall(r"\b([a-z][a-z0-9_]*)\s*:", literal_body))

    # Step 3: `normalized.<key> = ` assignments outside the literal
    assignment_keys = set(re.findall(r"\bnormalized\.([a-z][a-z0-9_]*)\s*=", func_body))

    frontend_fields = literal_keys | assignment_keys
    assert frontend_fields, (
        f"Parsed zero fields from normalizeBasemapConfig in {BASEMAP_UTILS_TS}. "
        f"The parser may have stopped matching — check the regex against the current source."
    )
    return frontend_fields


def test_normalize_basemap_preserve_set_subset_of_backend():
    """Frontend normalizeBasemapConfig preserve-set must be a subset of backend BasemapConfig fields.

    Contract direction (GUARD-02):
      frontend_preserve_set ⊆ backend_fields

    Every field the frontend writes into the `normalized` object and sends to
    the backend must be declared by `BasemapConfig`. If a new field is added
    to the frontend function without a matching backend field declaration, the
    backend rejects it with a 422 (extra='forbid'). This test catches that
    drift in CI before it ships.

    Current state (v1041): frontend and backend sets are equal (all 11 fields
    declared in both). The subset direction is the 422-safety invariant.
    """
    frontend_fields = _parse_frontend_basemap_preserve_set()
    backend_fields = set(BasemapConfig.model_fields.keys())

    only_in_frontend = frontend_fields - backend_fields

    assert not only_in_frontend, (
        f"GUARD-02 DRIFT: normalizeBasemapConfig in basemap-utils.ts writes "
        f"fields that BasemapConfig (extra='forbid') does not declare.\n"
        f"\n"
        f"Fields only in frontend (backend will 422 on save):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: either add the missing fields to BasemapConfig in\n"
        f"  backend/app/modules/catalog/maps/schemas.py\n"
        f"or remove them from normalizeBasemapConfig in\n"
        f"  frontend/src/lib/basemap-utils.ts"
    )


def test_basemap_config_extra_forbid_retained():
    """BasemapConfig must retain `extra='forbid'` so the subset guard remains meaningful.

    If `extra` is weakened to `'ignore'` or removed, the backend silently
    accepts unknown fields — making this guard's safety premise untrue.
    This assertion fails loudly if that happens so the architectural change
    is visible in CI.
    """
    extra = BasemapConfig.model_config.get("extra")
    assert extra == "forbid", (
        f"BasemapConfig.model_config['extra'] is {extra!r}, expected 'forbid'.\n"
        f"Weakening extra breaks the GUARD-02 safety premise: the backend would "
        f"silently accept unknown fields from normalizeBasemapConfig instead of "
        f"returning 422. If this change was intentional, update GUARD-02 to "
        f"reflect the new validation contract."
    )

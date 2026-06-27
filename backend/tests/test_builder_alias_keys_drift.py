"""Static-analysis test: the frontend builder snake_case->camelCase alias map
must stay identical to the backend's authoritative inverse.

Contract (builder-audit DRY-03 / SPEC-08):
  The builder block keys are authored in camelCase on the frontend but stored
  snake_case. Both sides translate between the two, and historically the
  mapping was hand-maintained in four places (frontend ``shared.ts`` +
  ``normalize-style-config.ts``, backend ``schemas.py`` + ``style_json.py``)
  with already-divergent contents (the folder_group_* gap).

  After consolidation there is ONE frontend alias map
  (``BUILDER_STYLE_KEY_ALIASES`` in
  ``frontend/src/components/builder/layer-adapters/shared.ts``, snake->camel)
  and ONE backend authoritative table
  (``_BUILDER_CAMEL_TO_SNAKE_KEYS`` in ``schemas.py``, with its derived inverse
  ``BUILDER_SNAKE_TO_CAMEL_KEYS``). This guard asserts the two snake->camel maps
  are byte-for-byte equal so a new builder key added to one side without the
  other is caught in CI rather than at save/export time.

  Fail-before is provable: drop or rename any entry in either map and the
  equality assertion names the offending key.
"""

from __future__ import annotations

import re

from app.modules.catalog.maps.schemas import BUILDER_SNAKE_TO_CAMEL_KEYS
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SHARED_TS = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "builder"
    / "layer-adapters"
    / "shared.ts"
)


def _parse_frontend_alias_map() -> dict[str, str]:
    """Parse the BUILDER_STYLE_KEY_ALIASES object literal from the TS source.

    Matches the body between ``BUILDER_STYLE_KEY_ALIASES ... = {`` and the
    closing ``};`` then extracts every ``snake_key: 'camelValue'`` pair.
    Static analysis only — does not import or execute TypeScript.
    """
    source = SHARED_TS.read_text(encoding="utf-8")
    match = re.search(
        r"BUILDER_STYLE_KEY_ALIASES\s*:\s*Record<string,\s*string>\s*=\s*\{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    assert match, (
        f"Could not find `BUILDER_STYLE_KEY_ALIASES: Record<string, string> = "
        f"{{...}}` in {SHARED_TS}. The drift guard cannot run without it. If the "
        f"constant was renamed or moved, update this test accordingly."
    )
    body = match.group(1)
    pairs = re.findall(r"""(\w+)\s*:\s*['"]([^'"]+)['"]""", body)
    assert pairs, (
        f"Regex matched the BUILDER_STYLE_KEY_ALIASES body in {SHARED_TS} but "
        f"found no key/value pairs inside it. The parser may be broken."
    )
    return {snake: camel for snake, camel in pairs}


def test_builder_alias_map_parity():
    """Frontend BUILDER_STYLE_KEY_ALIASES must equal backend BUILDER_SNAKE_TO_CAMEL_KEYS.

    Both are snake_case->camelCase. A divergence means a builder style key would
    round-trip to a different camelCase name on one side, silently breaking the
    save->reload->export path.
    """
    frontend = _parse_frontend_alias_map()
    backend = dict(BUILDER_SNAKE_TO_CAMEL_KEYS)

    only_frontend = set(frontend) - set(backend)
    only_backend = set(backend) - set(frontend)
    mismatched = {
        k: (frontend[k], backend[k])
        for k in set(frontend) & set(backend)
        if frontend[k] != backend[k]
    }

    assert frontend == backend, (
        "builder-audit DRY-03/SPEC-08 DRIFT: the frontend builder alias map and "
        "the backend inverse have diverged.\n"
        f"\nKeys only in frontend (shared.ts): {sorted(only_frontend)}"
        f"\nKeys only in backend (schemas.py): {sorted(only_backend)}"
        f"\nKeys mapping to different camelCase (frontend, backend): {mismatched}"
        "\n\nFix: reconcile BUILDER_STYLE_KEY_ALIASES in\n"
        "  frontend/src/components/builder/layer-adapters/shared.ts\n"
        "and _BUILDER_CAMEL_TO_SNAKE_KEYS in\n"
        "  backend/app/modules/catalog/maps/schemas.py\n"
        "so the snake<->camel mapping is identical on both sides."
    )

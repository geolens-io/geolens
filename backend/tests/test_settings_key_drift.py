"""Static-analysis test: every settings-key literal the admin frontend sends
or reads must be a member of the backend PersistentConfig registry.

Contract (codebase audit 2026-08-30 (8dc529f17), "The settings channel ...
has no type, no OpenAPI enum, and no drift test"):
  ``updateSettings`` (frontend/src/api/settings.ts) takes a bare
  ``Record<string, unknown>`` and PUTs it to ``/settings/``. The registry map
  built in ``settings/router.py`` (``{cfg.key: cfg for cfg in _registry}``)
  does no key normalization, so a typo'd key either 400s on write
  (``Unknown setting key: ...``) or silently falls back to a field's
  hardcoded ``defaultValue`` on read (``useSettingsForm.ts``). That is exactly
  how ``branding_show_badge`` (frontend) vs. ``branding.show_badge`` (backend
  registry key) shipped in v1.17.0 — this repo already runs three sibling
  static guards of the same shape for capabilities, basemap config, and
  builder alias keys; this is the fourth.

  Contract direction: frontend_keys ⊆ backend_registry_keys. The backend may
  declare keys the frontend never surfaces (env-only or admin-API-only
  settings); that is not a bug.

  Fail-before is provable: rename ``'branding.show_badge'`` in
  ``updateBranding`` (api/settings.ts) back to ``'branding_show_badge'`` and
  this test fails, naming the offending key.
"""

from __future__ import annotations

import re

from app.core.persistent_config import _registry
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SETTINGS_TABS_DIR = REPO_ROOT / "frontend" / "src" / "components" / "admin" / "settings"
API_SETTINGS_TS = REPO_ROOT / "frontend" / "src" / "api" / "settings.ts"

_KEY_FIELD_RE = re.compile(r"key:\s*'([a-zA-Z0-9_.]+)'")
_FIND_SETTING_RE = re.compile(r"findSetting\(settings,\s*'([a-zA-Z0-9_.]+)'\)")
_SETTING_KEY_ATTR_RE = re.compile(r'settingKey="([a-zA-Z0-9_.]+)"')
_PAYLOAD_DOT_ASSIGN_RE = re.compile(r"\bsettings\.([a-zA-Z0-9_]+)\s*=")
_PAYLOAD_BRACKET_ASSIGN_RE = re.compile(
    r"""\bsettings\[['"]([a-zA-Z0-9_.]+)['"]\]\s*="""
)


def _parse_frontend_setting_keys() -> set[str]:
    """Parse every settings-key literal the admin frontend sends or reads.

    Two sources, matching the two ways a key literal reaches the wire:

    1. ``frontend/src/components/admin/settings/Settings*Tab.tsx`` — the
       ``useSettingsForm`` field defs (``key: '...'``), the read-back lookups
       (``findSetting(settings, '...')``), and the reset-badge wiring
       (``settingKey="..."``).
    2. ``frontend/src/api/settings.ts`` — the hand-built payload assignments
       in functions like ``updateBranding`` that construct a settings object
       without going through a ``useSettingsForm`` field def
       (``settings.foo = ...`` / ``settings['foo.bar'] = ...``).

    Static analysis only -- does not import or execute TypeScript.
    """
    keys: set[str] = set()

    tab_files = sorted(SETTINGS_TABS_DIR.glob("Settings*Tab.tsx"))
    assert tab_files, (
        f"Found zero Settings*Tab.tsx files under {SETTINGS_TABS_DIR}. "
        f"The parser may be broken, or the tabs moved."
    )
    for path in tab_files:
        source = path.read_text(encoding="utf-8")
        keys |= set(_KEY_FIELD_RE.findall(source))
        keys |= set(_FIND_SETTING_RE.findall(source))
        keys |= set(_SETTING_KEY_ATTR_RE.findall(source))

    api_source = API_SETTINGS_TS.read_text(encoding="utf-8")
    keys |= set(_PAYLOAD_DOT_ASSIGN_RE.findall(api_source))
    keys |= set(_PAYLOAD_BRACKET_ASSIGN_RE.findall(api_source))

    assert keys, (
        "Parsed zero settings keys from the admin settings frontend. The "
        "parser may have stopped matching -- check the regexes against the "
        "current source."
    )
    return keys


def test_frontend_setting_keys_subset_of_backend_registry():
    """Frontend settings-key literals must be a subset of the backend registry.

    Contract direction: frontend_keys ⊆ backend_registry_keys.

    A key the frontend sends that the registry does not declare 400s on
    write (``Unknown setting key: ...``) and is silently invisible on read
    (``findSetting`` returns undefined, the field renders its hardcoded
    default). If a new registry key is added without a matching frontend
    field, that is fine -- it is either env-only or intentionally
    admin-API-only.
    """
    frontend_keys = _parse_frontend_setting_keys()
    backend_keys = {cfg.key for cfg in _registry}

    only_in_frontend = frontend_keys - backend_keys

    assert not only_in_frontend, (
        f"Settings-key drift: the admin frontend references a key that "
        f"backend/app/core/persistent_config.py does not register.\n"
        f"\n"
        f"Keys only in frontend (backend will 400 on write, silently fall "
        f"back to defaultValue on read):\n"
        f"  {sorted(only_in_frontend)}\n"
        f"\n"
        f"Fix: either correct the frontend key literal in "
        f"frontend/src/components/admin/settings/ or frontend/src/api/settings.ts "
        f"to match the registry's key= value, or register the key in "
        f"backend/app/core/persistent_config.py."
    )

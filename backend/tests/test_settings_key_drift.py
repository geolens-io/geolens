"""Static-analysis test: every settings-key literal the admin frontend sends
or reads must be a member of the backend PersistentConfig registry.

fix(#1778): the settings channel (46 registry keys against ~120 hand-written
frontend literals) has no type, no OpenAPI enum, and no drift test.
``updateSettings`` (frontend/src/api/settings.ts) takes a bare
``Record<string, unknown>`` and PUTs it to ``/settings/``. The registry map
built in ``settings/router.py`` (``{cfg.key: cfg for cfg in _registry}``)
does no key normalization, so a typo'd key either 400s on write
(``Unknown setting key: ...``) or silently falls back to a field's
hardcoded ``defaultValue`` on read (``useSettingsForm.ts``). That is exactly
how ``branding_show_badge`` (frontend) vs. ``branding.show_badge`` (backend
registry key) shipped in v1.17.0 -- this repo already runs three sibling
static guards of the same shape for capabilities, basemap config, and
builder alias keys; this is the fourth.

Contract direction: frontend_keys is a subset of backend_registry_keys. The
backend may declare keys the frontend never surfaces (env-only or
admin-API-only settings); that is not a bug.

Most tab components go through ``useSettingsForm`` (``key: '...'`` field
defs, ``findSetting(settings, '...')`` reads, ``settingKey="..."`` reset
wiring). ``SettingsPermissionsTab.tsx`` is the one tab that bypasses that
hook entirely and talks to the settings item list, the save callback, and
the reset callback directly: ``settings.find((s) => s.key ===
'role_permissions')``, ``onSave({ role_permissions: matrix })``,
``onReset('role_permissions')``. A first version of this test only
recognized the ``useSettingsForm`` shapes, so a typo anywhere in that
direct-access tab would have kept passing while still producing the same
400-on-write / silent-default-on-read failure this guard exists to catch
(fix(#1778): review round 1). The parser below also walks every
``.find(...)``/``onSave(...)``/``onReset(...)`` call site and pulls out
whatever key literal reaches it, rather than only the field-def shape, so
a new hand-rolled access pattern is still covered.

Fail-before is provable two ways: rename ``'branding.show_badge'`` in
``updateBranding`` (api/settings.ts) back to ``'branding_show_badge'``, or
change the ``onReset('role_permissions')`` argument in
``SettingsPermissionsTab.tsx`` to a typo -- either fails this test, naming
the offending key.
"""

from __future__ import annotations

import re

from app.core.persistent_config import _registry
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SETTINGS_TABS_DIR = REPO_ROOT / "frontend" / "src" / "components" / "admin" / "settings"
API_SETTINGS_TS = REPO_ROOT / "frontend" / "src" / "api" / "settings.ts"
PERMISSIONS_TAB_TSX = SETTINGS_TABS_DIR / "SettingsPermissionsTab.tsx"

# useSettingsForm-mediated shapes: field defs, read-back lookups, reset wiring.
_KEY_FIELD_RE = re.compile(r"key:\s*'([a-zA-Z0-9_.]+)'")
_FIND_SETTING_RE = re.compile(r"findSetting\(settings,\s*'([a-zA-Z0-9_.]+)'\)")
_SETTING_KEY_ATTR_RE = re.compile(r'settingKey="([a-zA-Z0-9_.]+)"')

# Direct-access shapes (bypassing useSettingsForm): a raw `.find` read keyed
# on `.key === '...'`, every key literal in an `onSave({ ... })` payload, and
# the string argument to `onReset('...')`.
_DIRECT_FIND_RE = re.compile(
    r"\.find\(\s*\([^)]*\)\s*=>\s*[^)]*?\.key\s*===\s*'([a-zA-Z0-9_.]+)'"
)
_ON_SAVE_CALL_RE = re.compile(r"onSave\(\{(.*?)\}\)", re.DOTALL)
_ON_SAVE_KEY_RE = re.compile(r"([a-zA-Z0-9_.]+)\s*:")
_ON_RESET_CALL_RE = re.compile(r"onReset\('([a-zA-Z0-9_.]+)'\)")

# frontend/src/api/settings.ts hand-built payload assignments (updateBranding
# and any sibling that constructs a settings object without a field def).
_PAYLOAD_DOT_ASSIGN_RE = re.compile(r"\bsettings\.([a-zA-Z0-9_]+)\s*=")
_PAYLOAD_BRACKET_ASSIGN_RE = re.compile(
    r"""\bsettings\[['"]([a-zA-Z0-9_.]+)['"]\]\s*="""
)


def _parse_tab_source_keys(source: str) -> set[str]:
    """Every settings-key literal reachable from one Settings*Tab.tsx source,
    across both the useSettingsForm-mediated shapes and the direct
    find/save/reset call sites a tab may use instead.
    """
    keys: set[str] = set()
    keys |= set(_KEY_FIELD_RE.findall(source))
    keys |= set(_FIND_SETTING_RE.findall(source))
    keys |= set(_SETTING_KEY_ATTR_RE.findall(source))
    keys |= set(_DIRECT_FIND_RE.findall(source))
    keys |= set(_ON_RESET_CALL_RE.findall(source))
    for on_save_body in _ON_SAVE_CALL_RE.findall(source):
        keys |= set(_ON_SAVE_KEY_RE.findall(on_save_body))
    return keys


def _parse_frontend_setting_keys() -> set[str]:
    """Parse every settings-key literal the admin frontend sends or reads.

    Two sources, matching the two ways a key literal reaches the wire:

    1. ``frontend/src/components/admin/settings/Settings*Tab.tsx`` -- both
       the ``useSettingsForm`` shapes (field defs, ``findSetting`` reads,
       ``settingKey`` reset wiring) and the direct-access shapes a tab may
       use instead (``.find(... .key === '...')``, ``onSave({ ... })``,
       ``onReset('...')``).
    2. ``frontend/src/api/settings.ts`` -- the hand-built payload assignments
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
        keys |= _parse_tab_source_keys(path.read_text(encoding="utf-8"))

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

    Contract direction: frontend_keys is a subset of backend_registry_keys.

    A key the frontend sends that the registry does not declare 400s on
    write (``Unknown setting key: ...``) and is silently invisible on read
    (``findSetting``/``.find`` returns undefined, the field renders its
    hardcoded default or nothing at all). If a new registry key is added
    without a matching frontend field, that is fine -- it is either
    env-only or intentionally admin-API-only.
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


def test_parser_floor_and_permissions_tab_positive_control():
    """Guard the parser itself, not just the drift it looks for.

    Two properties, so a broken or narrowed parser fails loudly instead of
    quietly passing an empty or shrunken subset check:

    1. Positive control: ``SettingsPermissionsTab.tsx`` reaches
       ``role_permissions`` only through the direct-access shapes
       (``.find(... .key === 'role_permissions')``, ``onSave({
       role_permissions: matrix })``, ``onReset('role_permissions')``) --
       none of the ``useSettingsForm`` shapes appear in that file. If any of
       the three direct-access regexes regresses, this key drops out and
       the assertion below names it.
    2. Floor: the combined frontend key count must not fall below the
       current count. A regression that breaks one of the six extraction
       regexes silently shrinks the set the subset check runs against,
       which would make ``test_frontend_setting_keys_subset_of_backend_registry``
       pass vacuously instead of catching real drift.
    """
    permissions_source = PERMISSIONS_TAB_TSX.read_text(encoding="utf-8")

    direct_find_keys = set(_DIRECT_FIND_RE.findall(permissions_source))
    on_reset_keys = set(_ON_RESET_CALL_RE.findall(permissions_source))
    on_save_keys: set[str] = set()
    for on_save_body in _ON_SAVE_CALL_RE.findall(permissions_source):
        on_save_keys |= set(_ON_SAVE_KEY_RE.findall(on_save_body))

    assert "role_permissions" in direct_find_keys, (
        "Positive control failed: the direct-.find() regex no longer finds "
        "'role_permissions' in SettingsPermissionsTab.tsx's "
        "`settings.find((s) => s.key === 'role_permissions')` read."
    )
    assert "role_permissions" in on_save_keys, (
        "Positive control failed: the onSave(...) regex no longer finds "
        "'role_permissions' in SettingsPermissionsTab.tsx's "
        "`onSave({ role_permissions: matrix })` call."
    )
    assert "role_permissions" in on_reset_keys, (
        "Positive control failed: the onReset(...) regex no longer finds "
        "'role_permissions' in SettingsPermissionsTab.tsx's "
        "`onReset('role_permissions')` call."
    )

    # None of the useSettingsForm-mediated regexes should also fire on this
    # file -- if one starts matching, the file changed shape and the "one
    # tab bypasses useSettingsForm" premise in this test's docstring is
    # stale and needs re-reading, not silently absorbing.
    assert not _KEY_FIELD_RE.search(permissions_source)
    assert not _FIND_SETTING_RE.search(permissions_source)
    assert not _SETTING_KEY_ATTR_RE.search(permissions_source)

    frontend_keys = _parse_frontend_setting_keys()
    assert len(frontend_keys) >= 41, (
        f"Frontend settings-key count dropped to {len(frontend_keys)} "
        f"(expected at least 41). One of the extraction regexes likely "
        f"stopped matching -- a shrunken set makes the subset-of-registry "
        f"check pass vacuously instead of catching real drift.\n"
        f"Keys found: {sorted(frontend_keys)}"
    )

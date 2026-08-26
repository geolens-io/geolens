"""Every shipped default for the allowed-upload-extension list says the same thing.

fix(#1682 codex r2): adding a format to ``Settings.upload_allowed_extensions``
is not enough to ship it. Both compose files inject
``UPLOAD_ALLOWED_EXTENSIONS`` with a literal fallback, and an injected value
wins over the Settings default — so under the documented ``make dev`` and
production workflows the app enforces whatever the compose file says, not what
the code says. A change to one and not the others is invisible in review and
invisible at runtime: the new format simply never becomes uploadable, with no
error anywhere.

The list therefore has four shipped spellings that must agree:

  * ``Settings.upload_allowed_extensions`` — the code default, used only when
    nothing injects the variable;
  * ``docker-compose.yml`` — what ``make dev`` runs with;
  * ``docker-compose.prod.yml`` — what a self-hoster runs with;
  * ``.env.example`` — twice: the documented "Default:" line and the commented
    assignment beneath it.

The admin UI carries a fifth copy (``SettingsStorageTab.tsx``), which is a
client-side fallback for a response that omits the setting rather than
anything enforced, so it is checked here too but named separately.
"""

import re

import pytest

from app.core.config import settings
from tests.repo_paths import repo_root

ROOT = repo_root(__file__)

_COMPOSE_RE = re.compile(
    r'UPLOAD_ALLOWED_EXTENSIONS:\s*"\$\{UPLOAD_ALLOWED_EXTENSIONS:-([^}]*)\}"'
)
_ENV_DEFAULT_RE = re.compile(r"^#\s*Type: string \| Default: (\.[^\s]*)$", re.M)
_ENV_ASSIGN_RE = re.compile(r"^#\s*UPLOAD_ALLOWED_EXTENSIONS=(\S+)$", re.M)
_TSX_RE = re.compile(r"defaultValue:\s*'(\.zip[^']*)'")


def _normalize(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


CODE_DEFAULT = _normalize(settings.upload_allowed_extensions)


@pytest.mark.parametrize(
    "relative_path", ["docker-compose.yml", "docker-compose.prod.yml"]
)
def test_compose_fallback_matches_the_code_default(relative_path: str):
    """An injected value wins, so a stale compose fallback silently governs."""
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    matches = _COMPOSE_RE.findall(text)
    assert len(matches) == 1, (
        f"{relative_path}: expected exactly one UPLOAD_ALLOWED_EXTENSIONS "
        f"fallback, found {len(matches)}"
    )
    assert _normalize(matches[0]) == CODE_DEFAULT, (
        f"{relative_path} ships a different allowed-extension list than "
        "Settings.upload_allowed_extensions. Under this compose file the "
        "compose value is what the app enforces."
    )


def test_env_example_documents_the_code_default():
    """Both the 'Default:' comment and the commented assignment."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    section = text.split("Allowed file extensions for upload", 1)
    assert len(section) == 2, ".env.example no longer documents the upload list"
    body = section[1]

    documented = _ENV_DEFAULT_RE.search(body)
    assigned = _ENV_ASSIGN_RE.search(body)
    assert documented is not None, ".env.example lost its 'Default:' line"
    assert assigned is not None, ".env.example lost its commented assignment"
    assert _normalize(documented.group(1)) == CODE_DEFAULT
    assert _normalize(assigned.group(1)) == CODE_DEFAULT


def test_admin_ui_fallback_is_not_narrower_than_the_server():
    """The tab's fallback is cosmetic, but a stale one advertises less than
    the server accepts — the same confusion in a smaller place."""
    tsx = (
        ROOT
        / "frontend"
        / "src"
        / "components"
        / "admin"
        / "settings"
        / "SettingsStorageTab.tsx"
    ).read_text(encoding="utf-8")
    match = _TSX_RE.search(tsx)
    assert match is not None, "SettingsStorageTab lost its extension fallback"
    assert _normalize(match.group(1)) == CODE_DEFAULT


class TestDegradedConfigLookupFallbacks:
    """fix(#1682 codex r3): the DB-failure fallbacks, which had frozen literals.

    Both upload doors tolerate a persistent_config read failure by falling back
    to a hard-coded list. Those literals stayed put through two format
    additions, so during the exact hiccup they exist to survive, an upload of a
    supported format was refused for a reason nobody configured. They read from
    ``settings`` now; these tests drive the failure path rather than reading
    the source, so a future re-freeze fails here too.
    """

    async def test_upload_door_falls_back_to_the_configured_list(self, monkeypatch):
        from app.processing.ingest import router as ingest_router

        async def _boom(_db):
            raise RuntimeError("persistent_config unavailable")

        monkeypatch.setattr(ingest_router, "get_allowed_extensions_list", _boom)
        recovered = await ingest_router._get_allowed_extensions_safely(None)
        assert _normalize(",".join(recovered)) == CODE_DEFAULT

    def test_reupload_door_uses_the_same_source(self):
        """The presigned-reupload handler builds its fallback from the same
        property, so the two doors cannot answer differently."""
        from app.core.config import settings as live_settings

        assert _normalize(",".join(live_settings.allowed_extensions_list)) == (
            CODE_DEFAULT
        )
        source = (
            ROOT
            / "backend"
            / "app"
            / "modules"
            / "catalog"
            / "datasets"
            / "api"
            / "router_reupload.py"
        ).read_text(encoding="utf-8")
        assert "settings.allowed_extensions_list" in source, (
            "The presigned-reupload fallback stopped reading the configured "
            "list; a re-frozen literal will drift on the next format added."
        )


def test_the_tier1_formats_are_actually_in_the_code_default():
    """Guards the whole file against passing by agreeing on the wrong list."""
    for extension in (".fgb", ".kml", ".kmz", ".zip"):
        assert extension in CODE_DEFAULT


def test_regexes_would_notice_a_changed_list():
    """Counterfactual: the parsers read real values, not a constant."""
    assert _normalize("a, B ,,c") == ("a", "b", "c")
    assert _COMPOSE_RE.findall(
        'UPLOAD_ALLOWED_EXTENSIONS: "${UPLOAD_ALLOWED_EXTENSIONS:-.a,.b}"'
    ) == [".a,.b"]

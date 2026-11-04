"""The reader theme a branding extension sets on story and map responses."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.platform.extensions import _extensions
from app.platform.extensions import reader_theme as reader_theme_module
from app.platform.extensions.defaults import DefaultBrandingExtension
from app.platform.extensions.protocols import BrandingExtension
from app.platform.extensions.reader_theme import ReaderTheme, current_reader_theme

THEME = {
    "accent": "#0a7f4f",
    "logo_url": "https://cdn.example.com/logo.svg",
    "font_family": "'Source Sans 3', sans-serif",
}


class _ThemedBranding:
    def __init__(self, theme: object) -> None:
        self.theme = theme

    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}

    def get_reader_theme(self) -> object:
        if isinstance(self.theme, Exception):
            raise self.theme
        return self.theme


class _LegacyBranding:
    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}


@pytest.fixture
def branding(monkeypatch: pytest.MonkeyPatch):
    """Registers a branding extension for one test and restores the slot."""
    monkeypatch.setattr(reader_theme_module, "_warned", False)
    previous = _extensions.get("branding")

    def register(ext: object) -> None:
        _extensions["branding"] = ext

    yield register
    if previous is None:
        _extensions.pop("branding", None)
    else:
        _extensions["branding"] = previous


def test_default_branding_satisfies_the_protocol_and_sets_no_theme():
    assert isinstance(DefaultBrandingExtension(), BrandingExtension)
    assert DefaultBrandingExtension().get_reader_theme() is None
    assert current_reader_theme() is None


def test_a_registered_theme_is_returned(branding):
    branding(_ThemedBranding(ReaderTheme(**THEME)))
    assert current_reader_theme() == ReaderTheme(**THEME)


@pytest.mark.parametrize(
    "values",
    [
        {"accent": "red"},
        {"accent": "#0a7f4"},
        {"accent": "#0a7f4f;color:red"},
        {"logo_url": "http://cdn.example.com/logo.svg"},
        {"logo_url": "data:image/svg+xml,<svg/>"},
        {"logo_url": "javascript:alert(1)"},
        {"logo_url": "https://user:pw@cdn.example.com/logo.svg"},
        {"logo_url": "https://cdn.example.com/" + "a" * 2000},
        {"font_family": "Inter; background: url(x)"},
        {"font_family": "Inter\\0"},
        {"font_family": "a" * 101},
        {"css": "body { color: red }"},
    ],
)
def test_a_theme_outside_the_allowed_set_is_refused(values, branding):
    with pytest.raises(ValidationError):
        ReaderTheme(**values)
    branding(_ThemedBranding(values))
    assert current_reader_theme() is None


def test_an_unvalidated_or_widened_instance_is_refused(branding):
    class Wider(ReaderTheme):
        css: str = "body { color: red }"

    branding(_ThemedBranding(ReaderTheme.model_construct(accent="red")))
    assert current_reader_theme() is None
    branding(_ThemedBranding(Wider(accent="#000000")))
    assert current_reader_theme() is None


def test_a_failing_extension_gives_no_theme_and_warns_once(branding, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(
        reader_theme_module.logger,
        "warning",
        lambda event, **_kw: warnings.append(event),
    )
    branding(_ThemedBranding(RuntimeError("overlay bug")))
    assert current_reader_theme() is None
    branding(_LegacyBranding())
    assert current_reader_theme() is None
    assert warnings == ["extensions.reader_theme.invalid"]


async def _reader_routes(client: AsyncClient, headers: dict) -> list[str]:
    created = await client.post(
        "/maps/", json={"name": f"theme-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    public = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )
    assert public.status_code == 200, public.text
    shared = await client.post(f"/maps/{map_id}/share/", headers=headers)
    assert shared.status_code == 200, shared.text
    story = await client.post("/stories/", json={"title": "Themed"}, headers=headers)
    assert story.status_code == 201, story.text
    return [
        f"/stories/{story.json()['id']}",
        f"/maps/shared/{shared.json()['token']}",
        f"/maps/{map_id}",
    ]


@pytest.mark.anyio
async def test_reader_routes_carry_the_theme_and_change_nothing_else(
    client: AsyncClient, admin_auth_header: dict, branding
):
    """Without an extension each route answers a null theme; with one, the
    same body plus the theme."""
    routes = await _reader_routes(client, admin_auth_header)
    plain = {}
    for path in routes:
        resp = await client.get(path, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        plain[path] = resp.json()
        assert plain[path]["reader_theme"] is None, path

    branding(_ThemedBranding(ReaderTheme(**THEME)))
    for path in routes:
        resp = await client.get(path, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        themed = resp.json()
        assert themed.pop("reader_theme") == THEME, path
        plain[path].pop("reader_theme")
        assert themed == plain[path], path


@pytest.mark.anyio
async def test_reader_routes_drop_an_invalid_theme(
    client: AsyncClient, admin_auth_header: dict, branding
):
    routes = await _reader_routes(client, admin_auth_header)
    branding(_ThemedBranding({**THEME, "accent": "url(x)"}))
    for path in routes:
        resp = await client.get(path, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert resp.json()["reader_theme"] is None, path

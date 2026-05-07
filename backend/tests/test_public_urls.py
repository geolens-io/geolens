from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import public_urls


@pytest.fixture(autouse=True)
def _reset_public_url_cache():
    """Reset the module-global URL cache around every test in this file.

    The cache short-circuits past AsyncMock dbs when populated by a prior test
    (audit 20260425 cluster 6), and conversely poisons later tests if this file
    leaves mock data behind. Reset both before and after to keep tests hermetic.
    """
    public_urls._PUBLIC_URL_CACHE = None
    yield
    public_urls._PUBLIC_URL_CACHE = None


def _make_request(
    *,
    headers: dict[str, str] | None = None,
    scheme: str = "https",
    netloc: str = "catalog.example.com",
    root_path: str = "",
):
    return SimpleNamespace(
        headers=headers or {},
        url=SimpleNamespace(scheme=scheme, netloc=netloc),
        scope={"root_path": root_path},
    )


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("https://catalog.example.com/", "https://catalog.example.com"),
        (" https://catalog.example.com/base/ ", "https://catalog.example.com/base"),
    ],
)
def test_normalize_public_url_strips_blank_values(
    raw_url: str | None, expected: str | None
) -> None:
    assert public_urls.normalize_public_url(raw_url) == expected


def test_api_suffix_helpers_preserve_existing_path_prefixes() -> None:
    assert (
        public_urls.append_api_suffix("https://catalog.example.com/geolens")
        == "https://catalog.example.com/geolens/api"
    )
    assert (
        public_urls.strip_api_suffix("https://catalog.example.com/geolens/api")
        == "https://catalog.example.com/geolens"
    )
    assert (
        public_urls.join_public_url("https://catalog.example.com/geolens/", "records")
        == "https://catalog.example.com/geolens/records"
    )


def test_request_origin_prefers_origin_then_referer_then_forwarded_host() -> None:
    assert (
        public_urls._request_origin(
            _make_request(headers={"origin": " https://catalog.example.com/ "})
        )
        == "https://catalog.example.com"
    )
    assert (
        public_urls._request_origin(
            _make_request(
                headers={"referer": "https://catalog.example.com/search?q=roads"}
            )
        )
        == "https://catalog.example.com"
    )
    assert (
        public_urls._request_origin(
            _make_request(
                headers={
                    "x-forwarded-proto": "http",
                    "x-forwarded-host": "forwarded.example.com:8443",
                }
            )
        )
        == "http://forwarded.example.com:8443"
    )


def test_request_origin_returns_none_without_host() -> None:
    assert (
        public_urls._request_origin(
            _make_request(headers={}, netloc="", scheme="https")
        )
        is None
    )


def test_resolve_public_api_url_prefers_explicit_configuration() -> None:
    assert (
        public_urls.resolve_public_api_url(
            "https://app.example.com",
            "https://api.example.com/",
            "https://legacy.example.com/api",
        )
        == "https://api.example.com"
    )
    assert (
        public_urls.resolve_public_api_url(
            None,
            None,
            "https://legacy.example.com/api/",
        )
        == "https://legacy.example.com/api"
    )
    assert (
        public_urls.resolve_public_api_url(
            "https://catalog.example.com/geolens/",
            None,
            None,
        )
        == "https://catalog.example.com/geolens/api"
    )


def test_resolve_public_api_url_uses_request_context_before_defaults() -> None:
    assert (
        public_urls.resolve_public_api_url(
            None,
            None,
            None,
            request=_make_request(
                headers={"origin": "https://catalog.example.com"},
                root_path="/proxy/api",
            ),
        )
        == "https://catalog.example.com/proxy/api"
    )
    assert (
        public_urls.resolve_public_api_url(
            None,
            None,
            None,
            request=_make_request(headers={}, netloc="catalog.example.com:8443"),
        )
        == "https://catalog.example.com:8443"
    )
    assert (
        public_urls.resolve_public_api_url(
            None,
            None,
            None,
            request=_make_request(headers={}, scheme="http", netloc="api:8000"),
        )
        == "http://localhost:8000"
    )


def test_resolve_public_app_url_prefers_configured_urls_and_request_origin() -> None:
    assert (
        public_urls.resolve_public_app_url(
            "https://catalog.example.com/",
            None,
            None,
        )
        == "https://catalog.example.com"
    )
    assert (
        public_urls.resolve_public_app_url(
            None,
            "https://catalog.example.com/api",
            None,
        )
        == "https://catalog.example.com"
    )
    assert (
        public_urls.resolve_public_app_url(
            None,
            None,
            None,
            request=_make_request(headers={"host": "catalog.example.com:8080"}),
        )
        == "https://catalog.example.com:8080"
    )
    assert (
        public_urls.resolve_public_app_url(
            None,
            "https://api-gateway.example.com/service",
            None,
        )
        == "https://api-gateway.example.com/service"
    )
    assert (
        public_urls.resolve_public_app_url(
            None,
            None,
            None,
            request=_make_request(headers={}, scheme="http", netloc="backend:8000"),
        )
        == "http://localhost:8080"
    )


def test_get_env_public_api_url_uses_current_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        public_urls.settings,
        "public_app_url",
        "https://catalog.example.com",
        raising=False,
    )
    monkeypatch.setattr(public_urls.settings, "public_api_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_base_url", None, raising=False)

    assert public_urls.get_env_public_api_url() == "https://catalog.example.com/api"


@pytest.mark.anyio
async def test_load_public_url_overrides_unwraps_json_values() -> None:
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        all=lambda: [
            (public_urls.PUBLIC_APP_URL_KEY, {"v": "https://catalog.example.com"}),
            (public_urls.PUBLIC_API_URL_KEY, "https://catalog.example.com/api"),
            (public_urls.LEGACY_PUBLIC_API_URL_KEY, None),
        ]
    )

    overrides = await public_urls._load_public_url_overrides(db)

    assert overrides == {
        public_urls.PUBLIC_APP_URL_KEY: "https://catalog.example.com",
        public_urls.PUBLIC_API_URL_KEY: "https://catalog.example.com/api",
        public_urls.LEGACY_PUBLIC_API_URL_KEY: None,
    }


@pytest.mark.anyio
async def test_get_public_urls_uses_db_overrides_when_env_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = AsyncMock(
        return_value={public_urls.PUBLIC_APP_URL_KEY: "https://catalog.example.com/"}
    )
    monkeypatch.delenv("ENV_ONLY_CONFIG", raising=False)
    monkeypatch.setattr(public_urls, "_load_public_url_overrides", loader)
    monkeypatch.setattr(public_urls.settings, "public_app_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_api_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_base_url", None, raising=False)

    app_url, api_url = await public_urls.get_public_urls(AsyncMock())

    assert (app_url, api_url) == (
        "https://catalog.example.com",
        "https://catalog.example.com/api",
    )
    loader.assert_awaited_once()


@pytest.mark.anyio
async def test_get_public_urls_skips_db_when_env_only_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = AsyncMock()
    monkeypatch.setenv("ENV_ONLY_CONFIG", "true")
    monkeypatch.setattr(public_urls, "_load_public_url_overrides", loader)
    monkeypatch.setattr(
        public_urls.settings,
        "public_app_url",
        "https://env.example.com",
        raising=False,
    )
    monkeypatch.setattr(public_urls.settings, "public_api_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_base_url", None, raising=False)

    app_url, api_url = await public_urls.get_public_urls(AsyncMock())

    assert (app_url, api_url) == (
        "https://env.example.com",
        "https://env.example.com/api",
    )
    loader.assert_not_awaited()


@pytest.mark.anyio
async def test_public_url_wrappers_delegate_to_get_public_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(
        return_value=("https://catalog.example.com", "https://catalog.example.com/api")
    )
    monkeypatch.setattr(public_urls, "get_public_urls", resolver)

    assert (
        await public_urls.get_public_app_url(AsyncMock())
        == "https://catalog.example.com"
    )
    assert (
        await public_urls.get_dataset_service_url(AsyncMock())
        == "https://catalog.example.com"
    )
    assert (
        await public_urls.get_public_api_url(AsyncMock())
        == "https://catalog.example.com/api"
    )


# ---------------------------------------------------------------------------
# Phase 268 H-27: for_external_use=True must reject request-origin fallback
# ---------------------------------------------------------------------------


def test_resolve_public_api_url_for_external_use_rejects_header_fallback() -> None:
    """H-27: when no PUBLIC_*_URL is configured, the for_external_use=True
    path must NOT fall back to attacker-controllable request headers."""
    request = _make_request(
        headers={"x-forwarded-host": "attacker.com", "x-forwarded-proto": "https"}
    )
    with pytest.raises(public_urls.PublicUrlNotConfiguredError):
        public_urls.resolve_public_api_url(
            None, None, None, request=request, for_external_use=True
        )


def test_resolve_public_api_url_for_external_use_rejects_origin_header() -> None:
    """H-27: ``Origin`` header alone is not enough for external-use URLs."""
    request = _make_request(headers={"origin": "https://attacker.com"})
    with pytest.raises(public_urls.PublicUrlNotConfiguredError):
        public_urls.resolve_public_api_url(
            None, None, None, request=request, for_external_use=True
        )


def test_resolve_public_app_url_for_external_use_rejects_header_fallback() -> None:
    """H-27: same gate applies to the app URL resolver."""
    request = _make_request(headers={"origin": "https://attacker.com"})
    with pytest.raises(public_urls.PublicUrlNotConfiguredError):
        public_urls.resolve_public_app_url(
            None, None, None, request=request, for_external_use=True
        )


def test_resolve_public_api_url_for_external_use_accepts_explicit_app_url() -> None:
    """H-27: when PUBLIC_APP_URL is configured, the resolver succeeds even
    with for_external_use=True. The URL is derived from config, not headers."""
    request = _make_request(headers={"x-forwarded-host": "attacker.com"})
    result = public_urls.resolve_public_api_url(
        "https://app.example.com", None, None, request=request, for_external_use=True
    )
    assert result == "https://app.example.com/api"
    # Must NOT contain the attacker host
    assert "attacker.com" not in result


def test_resolve_public_api_url_for_external_use_accepts_explicit_api_url() -> None:
    """H-27: PUBLIC_API_URL is also acceptable explicit configuration."""
    request = _make_request(headers={"origin": "https://attacker.com"})
    result = public_urls.resolve_public_api_url(
        None,
        "https://api.example.com",
        None,
        request=request,
        for_external_use=True,
    )
    assert result == "https://api.example.com"


def test_resolve_public_app_url_for_external_use_accepts_explicit_config() -> None:
    """H-27: app URL resolver also succeeds with explicit config."""
    request = _make_request(headers={"origin": "https://attacker.com"})
    result = public_urls.resolve_public_app_url(
        "https://app.example.com",
        None,
        None,
        request=request,
        for_external_use=True,
    )
    assert result == "https://app.example.com"


def test_resolve_public_api_url_default_path_still_uses_request_origin() -> None:
    """Sanity: the existing for_external_use=False path is unchanged —
    request-origin fallback works for self-resolution use cases (OGC
    catalog landing-page links, etc.)."""
    request = _make_request(headers={"origin": "https://catalog.example.com"})
    result = public_urls.resolve_public_api_url(None, None, None, request=request)
    assert result == "https://catalog.example.com"


@pytest.mark.anyio
async def test_get_public_api_url_propagates_for_external_use_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H-27: the async wrapper must thread for_external_use through to
    the resolver. Otherwise the OAuth router's protection is silently
    a no-op."""
    monkeypatch.setattr(public_urls.settings, "public_app_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_api_url", None, raising=False)
    monkeypatch.setattr(public_urls.settings, "public_base_url", None, raising=False)
    loader = AsyncMock(return_value={})
    monkeypatch.delenv("ENV_ONLY_CONFIG", raising=False)
    monkeypatch.setattr(public_urls, "_load_public_url_overrides", loader)

    request = _make_request(headers={"origin": "https://attacker.com"})

    with pytest.raises(public_urls.PublicUrlNotConfiguredError):
        await public_urls.get_public_api_url(
            AsyncMock(), request=request, for_external_use=True
        )

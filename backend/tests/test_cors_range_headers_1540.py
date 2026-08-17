"""fix(#1540) review P2: CORS has to know the download route grew ranges.

#1528 gave ``/datasets/{id}/download/cog`` a HEAD, byte ranges, a strong
``ETag``, and ``If-Range``/``If-None-Match`` handling. A browser client on an
allowed origin could use none of it, because the middleware that decides what a
cross-origin caller may send and read had not changed:

- ``If-Range`` was not in ``Access-Control-Allow-Headers``, so the preflight for
  a resumable download was refused and the request never went out;
- ``ETag`` and ``Content-Range`` were not in ``Access-Control-Expose-Headers``,
  so on a request that did succeed the browser HID them from JavaScript. Not
  "undocumented" — unreadable. A client cannot resume against a validator it
  cannot see;
- ``HEAD`` was missing from ``Access-Control-Allow-Methods``, which is the one
  request a client makes to learn ranges are available at all.

The failure class is the wave's recurring one: a handler was extended and a
second component that has to agree with it was not. These tests are written
against the middleware's answers rather than the constant it builds them from,
so they fail for a client, not for a string.
"""

import pytest
from httpx import AsyncClient

_ORIGIN = "http://cors-1540.example.com"


@pytest.fixture
async def allowed_origin(client: AsyncClient, admin_auth_header: dict):
    """Put _ORIGIN in the allowlist and clear the module-global cache.

    The cache is a 30s module global keyed on nothing: a request in the last 30
    seconds leaves another test's allowlist in it, and the PUT does not
    invalidate it. Same guard, and same reason, as the sibling assertions in
    ``test_persistent_config.py``.
    """
    from app.api.middleware import cors as cors_middleware

    await client.put(
        "/settings/",
        json={"settings": {"cors_allowed_origins": _ORIGIN}},
        headers=admin_auth_header,
    )
    cors_middleware._origins_cache = (0.0, set())
    yield _ORIGIN
    cors_middleware._origins_cache = (0.0, set())


def _listed(header_value: str | None) -> set[str]:
    return {part.strip().lower() for part in (header_value or "").split(",")}


async def test_a_resumable_download_survives_preflight(
    client: AsyncClient, allowed_origin: str
):
    """The preflight a resuming browser client actually sends.

    ``If-Range`` and ``If-None-Match`` are not CORS-safelisted request headers,
    so this OPTIONS is not optional: the browser sends it first and refuses to
    issue the real request if the answer does not list them.
    """
    preflight = await client.options(
        "/datasets/00000000-0000-0000-0000-000000000000/download/cog",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "range, if-range, if-none-match",
        },
    )

    assert preflight.status_code == 200
    allowed = _listed(preflight.headers.get("access-control-allow-headers"))
    missing = {"range", "if-range", "if-none-match"} - allowed
    assert not missing, (
        f"the preflight refused {sorted(missing)}, so a cross-origin resumable "
        f"download never leaves the browser. Allowed: {sorted(allowed)}"
    )


async def test_head_is_an_allowed_method(client: AsyncClient, allowed_origin: str):
    """HEAD is how a client learns there are ranges to ask for.

    #1528 added the route's HEAD precisely so a client can probe before
    downloading. Omitting it here leaves that probe available to curl and GDAL
    and not to a browser.
    """
    preflight = await client.options(
        "/datasets/00000000-0000-0000-0000-000000000000/download/cog",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "HEAD",
        },
    )

    methods = _listed(preflight.headers.get("access-control-allow-methods"))
    assert "head" in methods, (
        f"HEAD is not an allowed method ({sorted(methods)}), so the probe this "
        f"route grew in #1528 is unavailable to any browser client."
    )


async def test_the_range_response_headers_are_readable_by_javascript(
    client: AsyncClient, allowed_origin: str, admin_auth_header: dict
):
    """A validator the caller cannot read is a validator it cannot use.

    Anything outside the CORS-safelisted response headers has to be named in
    ``Access-Control-Expose-Headers`` or the browser drops it before the caller
    sees it. ``ETag`` decides whether a resume is safe, ``Content-Range`` says
    which bytes arrived, and ``Accept-Ranges`` says ranges are possible at all.
    """
    resp = await client.get("/health", headers={"Origin": allowed_origin})

    exposed = _listed(resp.headers.get("access-control-expose-headers"))
    missing = {"etag", "content-range", "accept-ranges"} - exposed
    assert not missing, (
        f"{sorted(missing)} are not exposed, so JavaScript cannot read them "
        f"even when the response carries them. Exposed: {sorted(exposed)}"
    )


async def test_the_existing_cors_contract_is_unchanged(
    client: AsyncClient, allowed_origin: str
):
    """The vacuity guard: the additions must not have displaced anything.

    ``Access-Control-Allow-Headers`` and ``-Expose-Headers`` are single
    comma-separated strings, so appending to the wrong one, or replacing rather
    than extending, silently revokes access every other client depends on.
    """
    resp = await client.get("/health", headers={"Origin": allowed_origin})

    allowed = _listed(resp.headers.get("access-control-allow-headers"))
    exposed = _listed(resp.headers.get("access-control-expose-headers"))
    methods = _listed(resp.headers.get("access-control-allow-methods"))

    assert {"authorization", "content-type", "accept", "x-api-key"} <= allowed
    assert {"x-total-count", "link", "content-crs"} <= exposed
    assert {"get", "post", "put", "patch", "delete", "options"} <= methods
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert resp.headers.get("access-control-allow-origin") == allowed_origin

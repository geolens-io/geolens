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

import ast
import pathlib

import pytest
from httpx import AsyncClient

_ORIGIN = "http://cors-1540.example.com"

_ROUTE_SOURCE = pathlib.Path(__file__).resolve().parents[1] / (
    "app/modules/catalog/datasets/api/router_export.py"
)

# Fetch's CORS-safelisted response headers: readable by JavaScript without being
# named in Access-Control-Expose-Headers. Everything else the route sets has to
# be listed or the browser hides it from the caller.
_SAFELISTED_RESPONSE_HEADERS = {
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "expires",
    "last-modified",
    "pragma",
}


def _route_ast() -> ast.Module:
    return ast.parse(_ROUTE_SOURCE.read_text())


def _conditional_headers_the_route_reads() -> set[str]:
    """Every ``request.headers.get("...")`` in the module that gates on a validator.

    Module-wide rather than per-function: a conditional or range header read
    anywhere in this file is one a browser client has to be allowed to send.
    """
    found: set[str] = set()
    for node in ast.walk(_route_ast()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "headers"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            name = node.args[0].value.lower()
            if name == "range" or name.startswith("if-"):
                found.add(name)
    return found


def _response_headers_the_cog_route_sets() -> set[str]:
    """Header names in any ``headers=`` dict inside the COG download helpers.

    Scoped by the ``cog`` in the function names, which is the convention this
    route already follows, because the DCAT handlers in the same module set
    headers of their own that no browser client needs to read.

    Reads ``headers=`` keyword values specifically rather than every dict
    literal: the audit call in ``download_cog`` passes a ``details=`` dict whose
    keys include ``range``, and demanding that one be exposed would be nonsense.
    """
    found: set[str] = set()
    for node in ast.walk(_route_ast()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "cog" not in node.name:
            continue
        for inner in ast.walk(node):
            values = []
            if isinstance(inner, ast.keyword) and inner.arg == "headers":
                values.append(inner.value)
            elif isinstance(inner, ast.Assign) and any(
                isinstance(t, ast.Name) and "header" in t.id for t in inner.targets
            ):
                values.append(inner.value)
            elif isinstance(inner, ast.Assign) and any(
                isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name)
                and "header" in t.value.id
                and isinstance(t.slice, ast.Constant)
                for t in inner.targets
            ):
                found.update(
                    t.slice.value.lower()
                    for t in inner.targets
                    if isinstance(t, ast.Subscript)
                    and isinstance(t.slice, ast.Constant)
                )
            for value in values:
                for sub in ast.walk(value):
                    if isinstance(sub, ast.Dict):
                        found.update(
                            k.value.lower()
                            for k in sub.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        )
    return found


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


def _middleware_lists() -> tuple[set[str], set[str]]:
    """What the middleware actually answers, read off a response it writes."""
    from starlette.responses import Response

    from app.api.middleware.cors import DynamicCORSMiddleware

    resp = Response()
    DynamicCORSMiddleware._set_cors_headers(resp, _ORIGIN)
    return (
        _listed(resp.headers.get("access-control-allow-headers")),
        _listed(resp.headers.get("access-control-expose-headers")),
    )


def test_every_conditional_header_the_route_evaluates_is_allowed():
    """The coupling, enforced instead of remembered.

    This endpoint and this middleware have now drifted apart twice: #1528 gave
    the route a range contract the allow-list did not know about, that was
    fixed, and then the route grew ``If-Match`` and the allow-list did not learn
    about that either. Both times the symptom was invisible from the server —
    the endpoint worked perfectly, and a browser refused to send the request.

    So the link is a test rather than a habit. The header names come from the
    route's own source: any ``request.headers.get("if-…")`` or ``…("range")``
    it reads must be a header a cross-origin client is permitted to send. Add
    ``If-Unmodified-Since`` handling and this fails, naming it, before anyone
    has to notice a preflight failing in a console.
    """
    reads = _conditional_headers_the_route_reads()
    allowed, _ = _middleware_lists()

    assert {"range", "if-range", "if-none-match", "if-match"} <= reads, (
        f"the source scan found {sorted(reads)}, which is missing headers this "
        f"route is known to evaluate. The scan is broken, and a broken scan "
        f"passes this test for the wrong reason."
    )
    missing = reads - allowed
    assert not missing, (
        f"the route evaluates {sorted(missing)} but a cross-origin client may "
        f"not send them, so the preflight fails and the request never leaves "
        f"the browser. Add them to Access-Control-Allow-Headers in "
        f"app/api/middleware/cors.py."
    )


def test_every_response_header_the_route_sets_is_readable():
    """The other half of the same coupling.

    A response header outside Fetch's safelist is not merely undocumented to a
    cross-origin caller — it is invisible. The route can set a perfect ``ETag``
    and ``Content-Range`` and the browser will strip both before JavaScript
    sees them, which for a resumable download means the client cannot tell
    which version it holds or which bytes it just received.
    """
    sets = _response_headers_the_cog_route_sets()
    _, exposed = _middleware_lists()

    assert {"etag", "content-range", "accept-ranges", "content-disposition"} <= sets, (
        f"the source scan found {sorted(sets)}, which is missing headers this "
        f"route is known to set; a scan that finds nothing would pass this "
        f"test while proving nothing."
    )
    missing = sets - _SAFELISTED_RESPONSE_HEADERS - exposed
    assert not missing, (
        f"the route sets {sorted(missing)}, which a cross-origin caller cannot "
        f"read. Add them to Access-Control-Expose-Headers in "
        f"app/api/middleware/cors.py, or confirm they are CORS-safelisted."
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

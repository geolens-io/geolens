"""Bounded reads for a service-type probe's own request.

fix(#1770 round 41 P1). `probe_ogcapi`/`probe_wfs`/`probe_arcgis_service`/
`connect_stac_api` (and `_resolve_conformance`) used a plain `client.get`,
which buffers the whole body -- decompressed, if the service sends one --
before `.json()`/`.text` ever runs, with no byte cap, no decoded-size cap, and
no bound on how long any of it could take beyond the client's own
per-inactivity timeout. `assert_endpoints_stay_on_origin()`, which bounds all
of that, only runs AFTER `detect_service_type()` returns, so a protected
service a caller already holds a credential for could exhaust the API process
during a probe's own read, before that check ever gets a turn.

A separate module rather than a second function in `service_endpoints.py`:
`TestAServiceCannotPointTheCredentialSomewhereElse::test_the_validator_has_
exactly_one_request_site` and `TestBothModulesReadThroughOneRequestFunction::
test_only_fetch_document_talks_to_the_network` (`test_service_auth_transport_
1746.py`) both assert, structurally, that `fetch_document` is the ONLY
`client.<verb>(` call in `service_endpoints.py`/`service_items.py` -- a
hard-won invariant from review rounds r15-r23 that keeps the door's two
callers (the WFS/OGC API description check, and the item-page walk) from
growing a second, differently-protected read by accident. A probe's read is a
genuinely different caller with a genuinely different contract (see below),
not a THIRD accidental copy of the door's, so it lives outside the file those
tests scan rather than asking them to carve out an exception.
"""

import httpx

from app.platform.service_endpoints import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_ELEMENTS,
    MAX_DOCUMENT_TOKENS,
    read_bounded_body,
    require_decodable,
)


async def bounded_probe_read(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    accept: str,
) -> tuple[bytes, httpx.Headers]:
    """A probe's own read of a URL its caller already SSRF-validated.

    Bounded exactly as `fetch_document` bounds the door's own reads: the same
    `MAX_DOCUMENT_BYTES` on the wire (`read_bounded_body`, which streams via
    `aiter_raw` and stops the instant the cap is crossed), the same
    `MAX_DOCUMENT_TOKENS`/`MAX_DOCUMENT_ELEMENTS` decoded (`require_decodable`),
    identity-only so a compressed body is refused before a byte of it is
    inflated -- the compression-bomb defense `read_bounded_body`'s own
    docstring explains, extended here rather than reinvented. Raises
    `EndpointCheckFailedError` on any bound violation, alongside the
    `httpx.HTTPStatusError` `raise_for_status()` already raises for a non-2xx
    response; every caller already has (or, this round, gains) both in one
    except clause, since both mean the same thing to a probe: not this
    service, or not readable, degrade to `None`.

    Does NOT itself call `validate_url_for_ssrf`, unlike `fetch_document`.
    `fetch_document` re-validates because its caller (`_check_wfs`/
    `_check_ogcapi`) follows a CHAIN of server-CHOSEN addresses one page at a
    time, and each one needs its own check -- the whole reason a second
    validation immediately before each request buys anything there. A probe
    reads the single URL its own caller (the `/probe` or preview door)
    validated immediately before invoking it; there is no second address here
    for a second validation to catch that the first missed, so adding one
    would cost a request without bounding anything new.

    `headers` is keyword-only on purpose: `test_credential_producer_
    structural.py`'s walk of `modules/catalog/sources/` for a credential
    header reaching an outbound request is scope-local and keys off a literal
    `headers=`-shaped keyword argument on the call, not on the callee's
    parameter name or position, so a caller that passed this positionally
    would silently drop out of that walk's count.
    """
    request_headers = {**headers, "Accept": accept, "Accept-Encoding": "identity"}
    async with client.stream("GET", url, headers=request_headers) as response:
        response.raise_for_status()
        body = await read_bounded_body(response, MAX_DOCUMENT_BYTES)
        response_headers = response.headers
    require_decodable(
        body,
        accept=accept,
        token_budget=MAX_DOCUMENT_TOKENS,
        element_budget=MAX_DOCUMENT_ELEMENTS,
    )
    return body, response_headers

"""Bounded reads for a service-type probe's own request.

fix(#1770): `probe_ogcapi`/`probe_wfs`/`probe_arcgis_service`/
`connect_stac_api` used a plain `client.get` with no byte cap and no
decoded-size cap. `assert_endpoints_stay_on_origin()` only runs AFTER
`detect_service_type()` returns, so a probe's own read could exhaust the API
process before that check ever got a turn.

A separate module, not a second function in `service_endpoints.py`:
`test_service_auth_transport_1746.py` asserts, structurally, that
`fetch_document` is the ONLY `client.<verb>(` call in
`service_endpoints.py`/`service_items.py`, so its two callers never grow a
second, differently-protected read by accident. A probe's read has a
genuinely different contract (see `bounded_probe_read`), so it lives outside
the file those tests scan rather than asking them to carve out an exception.
"""

import httpx

from app.platform.service_endpoints import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_ELEMENTS,
    MAX_DOCUMENT_TOKENS,
    read_bounded_body,
    require_decodable,
)


async def bounded_probe_exchange(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    accept: str,
    json_body: object | None = None,
    raise_for_status: bool = True,
) -> tuple[bytes, httpx.Response]:
    """A probe's own request to a URL its caller already SSRF-validated.

    Bounded exactly as `fetch_document` bounds the door's reads: the same
    `MAX_DOCUMENT_BYTES` on the wire (`read_bounded_body`, streamed via
    `aiter_raw`, stopped the instant the cap is crossed), the same
    `MAX_DOCUMENT_TOKENS`/`MAX_DOCUMENT_ELEMENTS` decoded (`require_decodable`),
    identity-only so a compressed body can't be used as a bomb. Raises
    `EndpointCheckFailedError` on any bound violation, alongside the
    `httpx.HTTPStatusError` `raise_for_status()` raises for a non-2xx
    response; every caller catches both in one except clause, since both mean
    the same thing to a probe: not this service, degrade to `None`.

    The byte and token bounds do not limit how long the read takes, so a
    caller that needs a deadline wraps the call in one.

    Redirects are followed here, not by httpx: with `follow_redirects` on,
    httpx reads each redirect response's body in full, decoded, before the
    caps above can see it. Each redirect response is closed unread instead,
    and the next hop is the request httpx built for it, so the client's
    response hook still validates every hop and httpx still drops
    `Authorization` across origins. The hop limit is the client's own
    `max_redirects`.

    Returns the body and the closed response, whose `url` is the address the
    body came from after any redirect, whose `history` holds the closed
    redirect responses, and whose `headers` are the final response's.
    `json_body` is sent as a JSON request body. With `raise_for_status`
    false, a non-2xx response's body is read under the same bounds instead,
    for a caller that wants the error a service explains in it.

    Does NOT itself call `validate_url_for_ssrf`, unlike `fetch_document`.
    `fetch_document` re-validates because its caller follows a CHAIN of
    server-CHOSEN addresses one page at a time, and each one needs its own
    check. A probe reads the single URL its own caller (the `/probe` or
    preview door) validated immediately before invoking it; there is no
    second address here for a second validation to catch.

    `headers` is keyword-only on purpose: `test_credential_producer_
    structural.py`'s walk for a credential header reaching an outbound
    request keys off a literal `headers=`-shaped keyword argument, not the
    callee's parameter name or position, so a positional call would silently
    drop out of that walk's count.
    """
    request_headers = {**headers, "Accept": accept, "Accept-Encoding": "identity"}
    # A marker covers only the one-line call directly below it, so a comment
    # or a wrapped argument list in between leaves the call unsuppressed.
    # codeql[py/full-ssrf] the caller validated this exact URL with validate_url_for_ssrf immediately before invoking bounded_probe_exchange, and the client comes from make_safe_client, whose transport re-resolves, validates and pins the IP at connect time and whose response hook revalidates every redirect hop
    request = client.build_request(method, url, headers=request_headers, json=json_body)
    redirects: list[httpx.Response] = []
    while True:
        # codeql[py/full-ssrf] the request built and validated above, or the next hop the client built for a redirect it already revalidated
        response = await client.send(request, stream=True, follow_redirects=False)
        try:
            if response.next_request is None:
                response.history = redirects
                if raise_for_status:
                    response.raise_for_status()
                body = await read_bounded_body(response, MAX_DOCUMENT_BYTES)
                break
            redirects.append(response)
            if len(redirects) > client.max_redirects:
                raise httpx.TooManyRedirects(
                    "Exceeded maximum allowed redirects.",
                    request=response.next_request,
                )
            request = response.next_request
        finally:
            await response.aclose()
    require_decodable(
        body,
        accept=accept,
        token_budget=MAX_DOCUMENT_TOKENS,
        element_budget=MAX_DOCUMENT_ELEMENTS,
    )
    return body, response


async def bounded_probe_read(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    accept: str,
    raise_for_status: bool = True,
) -> tuple[bytes, httpx.Headers]:
    """A GET through `bounded_probe_exchange`, for callers that want the body
    and the response headers and nothing else."""
    body, response = await bounded_probe_exchange(
        client,
        "GET",
        url,
        headers=headers,
        accept=accept,
        raise_for_status=raise_for_status,
    )
    return body, response.headers

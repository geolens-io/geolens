"""Cache and conditional-response helpers shared by tile route families."""

from __future__ import annotations

import hashlib

from fastapi import Request, Response, status


def _tile_headers(cache_scope: str, cache_ttl: int) -> dict[str, str]:
    return {
        "Content-Encoding": "gzip",
        "Cache-Control": f"{cache_scope}, max-age={cache_ttl}",
        "Access-Control-Allow-Origin": "*",
    }


def _empty_tile_headers(cache_scope: str, cache_ttl: int) -> dict[str, str]:
    """Return cache and CORS headers for an empty (204) MVT tile."""
    return {
        "Cache-Control": f"{cache_scope}, max-age={cache_ttl}",
        "Access-Control-Allow-Origin": "*",
    }


def _serving_tile_headers(
    cache_scope: str,
    cache_ttl: int,
    cache_control_override: str | None,
    *,
    empty: bool = False,
) -> dict[str, str]:
    """Apply hosted cache policy only to responses already safe for sharing.

    Signed, embed-token, and unpublished preview tiles resolve to ``private``.
    A serving extension must never turn those into publicly cacheable CDN
    responses. Public tiles may use the provider's CDN-specific TTL.
    """
    headers = (
        _empty_tile_headers(cache_scope, cache_ttl)
        if empty
        else _tile_headers(cache_scope, cache_ttl)
    )
    if cache_scope == "public" and cache_control_override is not None:
        headers["Cache-Control"] = cache_control_override
    return headers


def _tile_etag(content: bytes) -> str:
    """Return a strong, content-addressed ETag for served tile bytes."""
    return '"' + hashlib.sha256(content).hexdigest()[:32] + '"'


def _if_none_match_satisfied(if_none_match: str | None, etag: str) -> bool:
    """Return whether an If-None-Match value matches the current tile ETag."""
    if not if_none_match:
        return False
    value = if_none_match.strip()
    if value == "*":
        return True
    candidates = {
        candidate.strip().removeprefix("W/") for candidate in value.split(",")
    }
    return etag.removeprefix("W/") in candidates


def _tile_response(
    request: Request, content: bytes, base_headers: dict[str, str]
) -> Response:
    """Build an MVT response with ETag-based conditional-request support."""
    etag = _tile_etag(content)
    if _if_none_match_satisfied(request.headers.get("if-none-match"), etag):
        conditional_headers = {
            key: value
            for key, value in base_headers.items()
            if key.lower() != "content-encoding"
        }
        conditional_headers["ETag"] = etag
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=conditional_headers,
        )
    return Response(
        content=content,
        media_type="application/vnd.mapbox-vector-tile",
        headers={**base_headers, "ETag": etag},
    )

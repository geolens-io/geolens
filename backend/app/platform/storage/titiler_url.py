"""Single source of truth for Titiler proxy URL construction (REMED-04 / P2-01).

Three callers build URLs against the internal Titiler service:
- processing/tiles/router.py (cog/tiles/{z}/{x}/{y}.{fmt} for the raster
  tile proxy lane)
- modules/catalog/sources/stac_router.py (cog/info + cog/statistics for
  STAC import band/dtype probing)

Centralizing the host + path build here means:
1. A future env-driven override (TITILER_BASE_URL) needs to change one line
2. URL encoding of the user-supplied `url` query parameter is consistent
   across callers — no f-string concatenation that could escape-mismatch
3. Test infrastructure has a single seam to mock for unit tests

Naming choice: this module is `titiler_url.py`, not `cog_url.py`. Despite the
URL path being `/cog/...`, the host is the *Titiler* service, and the
asset_uri ALSO appears in `router_export.py` (RedirectResponse) which is a
separate concern (signed export URL, not Titiler routing). Conflating both
under `cog_url.py` would mislead future readers.

NOTE: Titiler is currently internal-only (no `ports:` block in docker-compose).
If that ever changes, the security stance at tiles/router.py::_titiler_client
(SEC-OBSV-01) and stac_router.py::_fetch_cog_info (SEC-OBSV-02) must be
re-audited — see the docstring contracts at those sites.
"""

from urllib.parse import urlencode

_TITILER_BASE_URL = "http://titiler:8000"


def build_titiler_cog_url(
    endpoint: str,
    *,
    query: dict[str, str] | None = None,
    raw_query_suffix: str | None = None,
) -> str:
    """Build a Titiler COG-endpoint URL.

    Args:
        endpoint: Path segment after /cog/ (e.g. "info", "statistics",
            "tiles/WebMercatorQuad/5/10/15.png"). Must NOT start with "/".
        query: dict of query parameters — values are URL-encoded.
            Use this for caller-supplied user-input parameters like `url=...`.
        raw_query_suffix: pre-built query string fragment without the
            leading "?". Use this for upstream-rendered fragments that
            already URL-encode their values and may contain repeated keys
            (e.g. bidx=1&bidx=2&bidx=3 from _titiler_render_params).

    Returns:
        Fully-built URL string.
    """
    base = f"{_TITILER_BASE_URL}/cog/{endpoint}"
    parts: list[str] = []
    if query:
        parts.append(urlencode(query))
    if raw_query_suffix:
        parts.append(raw_query_suffix.lstrip("?&"))
    if not parts:
        return base
    return f"{base}?{'&'.join(parts)}"

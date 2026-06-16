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

# IN-01 (Phase 1210): honour the env-overridable TITILER_BASE_URL setting.
# The module docstring promised "a future env-driven override (TITILER_BASE_URL)
# needs to change one line" — this is that line.  The value is read lazily
# (inside build_titiler_cog_url) so the module can be imported before the
# FastAPI app fully initialises settings.
# Default kept as "http://titiler:8000" for byte-identical behaviour with the
# previous hardcoded constant when the env var is absent.
_TITILER_BASE_URL: str | None = None  # populated lazily on first call


def _get_titiler_base_url() -> str:
    """Return the Titiler base URL, honouring TITILER_BASE_URL env override.

    Lazily resolved on first call so that importing this module before
    the FastAPI settings object is ready does not raise a boot error.
    """
    global _TITILER_BASE_URL
    if _TITILER_BASE_URL is None:
        from app.core.config import settings

        _TITILER_BASE_URL = settings.titiler_base_url
    return _TITILER_BASE_URL


# WR-01 (Phase 1210): blocked substring patterns for path-traversal defense.
# These are checked BEFORE building any VSI path so no provider-specific
# handling is required.  The check is defense-in-depth: asset_uri values are
# set by the ingest tasks (not user-controlled at the tile-serve call site),
# but a compromised DB row or future injection should not reach GDAL.
_BLOCKED_ASSET_URI_PATTERNS: tuple[str, ...] = (
    "..",  # path traversal (relative or absolute)
)


def _validate_asset_uri(asset_uri: str) -> None:
    """Raise ValueError if asset_uri contains path-traversal or injection patterns.

    Defense-in-depth: asset_uri comes from the DB (set by ingest tasks), so
    exploitation requires a prior DB write compromise.  This guard ensures a
    compromised or malformed asset_uri cannot escape the tenant prefix into
    another tenant's namespace or outside the bucket/container.

    Checked patterns (WR-01):
    - ``..`` segment — POSIX traversal (``../../etc/passwd``).
    - Leading ``/``  — absolute path (skips the bucket/staging prefix).
    - Embedded scheme-like strings (``://``, ``/vsicurl/``, ``/vsis3/``,
      ``/vsiaz/``) — would reconstruct a raw VSI path bypassing the seam.

    http(s):// URLs are exempt — they go through the STAC pass-through branch
    which returns them unchanged; no VSI prefix is built.
    """
    if asset_uri.startswith("/"):
        raise ValueError(
            f"asset_uri must be a relative logical key, got absolute path: {asset_uri!r}"
        )
    if ".." in asset_uri:
        raise ValueError(f"asset_uri contains path-traversal segment: {asset_uri!r}")
    # Block embedded VSI scheme injection — an asset_uri that itself looks like
    # a VSI path or URL scheme would escape the VSI prefix built by this function.
    for blocked in ("://", "/vsicurl/", "/vsis3/", "/vsiaz/"):
        if blocked in asset_uri:
            raise ValueError(
                f"asset_uri contains disallowed pattern {blocked!r}: {asset_uri!r}"
            )


def resolve_open_path(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """Resolve a logical asset_uri to a GDAL-open-able VSI path.

    Single source of truth for VSI prefix construction (STOR-01 / Phase 1210).
    A provider swap (s3->azure->local) changes ONLY this function.

    tenant_id: when provided (multi_tenant mode), prepend tenants/{tenant_id}/
               to the key for the provider's namespace. In single_tenant this
               argument is always None and asset_uri is used verbatim (byte-identical
               with the previous inline VSI blocks in tiles/router.py and vrt.py).

    Provider dispatch:
      local  -> {upload_staging_dir}/{asset_uri}  (absolute filesystem path)
      s3     -> /vsis3/{s3_bucket}/{asset_uri}
      azure  -> /vsiaz/{azure_storage_container}/{asset_uri}
      remote -> asset_uri unchanged (already a full URL — STAC import path)

    Raises:
        ValueError: If asset_uri contains path-traversal or injection patterns
            (WR-01 defense-in-depth, applied BEFORE VSI prefix construction).
    """
    from app.core.config import settings

    # Remote STAC import: asset_uri is already a full URL — pass through unchanged.
    if asset_uri.startswith("http://") or asset_uri.startswith("https://"):
        return asset_uri

    # WR-01: validate BEFORE building any VSI path.
    _validate_asset_uri(asset_uri)

    # In multi_tenant mode, key is prefixed by tenant namespace.
    # In single_tenant, tenant_id is None and key = asset_uri (byte-identical).
    key = f"tenants/{tenant_id}/{asset_uri}" if tenant_id else asset_uri

    provider = settings.storage_provider
    if provider == "s3":
        return f"/vsis3/{settings.s3_bucket}/{key}"
    if provider == "azure":
        return f"/vsiaz/{settings.azure_storage_container}/{key}"
    # local (default) — use bare asset_uri (NOT key) to stay byte-identical
    # with the existing local path: {upload_staging_dir}/{asset_uri}
    return f"{settings.upload_staging_dir}/{asset_uri}"


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
    base = f"{_get_titiler_base_url()}/cog/{endpoint}"
    parts: list[str] = []
    if query:
        parts.append(urlencode(query))
    if raw_query_suffix:
        parts.append(raw_query_suffix.lstrip("?&"))
    if not parts:
        return base
    return f"{base}?{'&'.join(parts)}"

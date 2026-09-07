"""Single source of truth for Titiler proxy URL construction (REMED-04/P2-01).

Callers: processing/tiles/router.py (raster tile proxy) and
modules/catalog/sources/stac_router.py (cog/info, cog/statistics for STAC
band/dtype probing). Centralizing here means one place for a future
TITILER_BASE_URL override, consistent URL-encoding of the `url` query
param, and one seam to mock in tests.

Named `titiler_url.py`, not `cog_url.py`: the host is the Titiler service
even though the path is `/cog/...`, and `asset_uri` also appears in
router_export.py for a different concern (signed export redirect).

Titiler is currently internal-only (no `ports:` in docker-compose). If that
changes, re-audit the security stance at tiles/router.py::_titiler_client
(SEC-OBSV-01) and sources/cog_info.py::fetch_cog_info (SEC-OBSV-02); see
#1927.
"""

from urllib.parse import urlencode

# IN-01: env-overridable TITILER_BASE_URL, read lazily (in
# _get_titiler_base_url) so the module can import before FastAPI settings
# are ready. Defaults to "http://titiler:8000" when unset.
_TITILER_BASE_URL: str | None = None  # populated lazily on first call


def _get_titiler_base_url() -> str:
    """Return the Titiler base URL, honouring TITILER_BASE_URL env override.

    Lazily resolved so importing this module before settings are ready
    doesn't raise a boot error.
    """
    global _TITILER_BASE_URL
    if _TITILER_BASE_URL is None:
        from app.core.config import settings

        _TITILER_BASE_URL = settings.titiler_base_url
    return _TITILER_BASE_URL


# WR-01: path-traversal defense, checked before any VSI path is built.
# Defense-in-depth — asset_uri is DB-set by ingest, not user-controlled here.
_BLOCKED_ASSET_URI_PATTERNS: tuple[str, ...] = (
    "..",  # path traversal (relative or absolute)
)


def _validate_asset_uri(asset_uri: str) -> None:
    """Raise ValueError if asset_uri contains path-traversal or injection patterns.

    Defense-in-depth: asset_uri comes from the DB (ingest-set), so
    exploitation needs a prior DB write compromise; this guard stops a
    compromised or malformed value from escaping the tenant prefix.

    Checked (WR-01): ``..`` traversal, a leading ``/`` (absolute path), and
    embedded scheme-like strings (``://``, ``/vsicurl/``, ``/vsis3/``,
    ``/vsiaz/``) that would reconstruct a raw VSI path. http(s):// URLs are
    exempt — they pass through the STAC branch unchanged.
    """
    if asset_uri.startswith("/"):
        raise ValueError(
            f"asset_uri must be a relative logical key, got absolute path: {asset_uri!r}"
        )
    if ".." in asset_uri:
        raise ValueError(f"asset_uri contains path-traversal segment: {asset_uri!r}")
    # Block embedded VSI/scheme injection that would escape the built prefix.
    for blocked in ("://", "/vsicurl/", "/vsis3/", "/vsiaz/"):
        if blocked in asset_uri:
            raise ValueError(
                f"asset_uri contains disallowed pattern {blocked!r}: {asset_uri!r}"
            )


def resolve_storage_key(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """Resolve a logical DB asset URI to its physical provider key.

    Managed raster/VRT assets are stored under ``tenants/{tenant_id}/`` in
    multi-tenant mode while the catalog persists a tenant-agnostic logical
    URI. Every direct storage operation must cross this seam before touching
    the provider. Remote STAC URLs are already physical and pass through
    unchanged.
    """
    if asset_uri.startswith("http://") or asset_uri.startswith("https://"):
        return asset_uri

    _validate_asset_uri(asset_uri)
    from app.core.tenancy import is_multi_tenant

    if is_multi_tenant() and tenant_id is None:
        raise RuntimeError(
            "Managed storage access requires tenant context in multi-tenant mode"
        )
    return f"tenants/{tenant_id}/{asset_uri}" if tenant_id else asset_uri


def resolve_current_storage_key(asset_uri: str) -> str:
    """Resolve a logical key for the active request or worker tenant.

    Storage-facing code must use this rather than reading
    ``current_tenant_var`` directly. Fails closed in multi-tenant mode via
    :func:`resolve_storage_key`; in single-tenant mode returns the logical
    key byte-for-byte even if a stray context value is present.
    """
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tenant_id = current_tenant_var.get() if is_multi_tenant() else None
    return resolve_storage_key(asset_uri, tenant_id=tenant_id)


def resolve_open_path(asset_uri: str, *, tenant_id: str | None = None) -> str:
    """Resolve a logical asset_uri to a GDAL-open-able VSI path.

    Single source of truth for VSI prefix construction (STOR-01). A provider
    swap (s3<->azure<->local) changes only this function.

    tenant_id: in multi_tenant mode, prepends ``tenants/{tenant_id}/`` to the
    key. In single_tenant mode it is always None and asset_uri is used as-is.

    Provider dispatch:
        local  -> {upload_staging_dir}/{asset_uri}
        s3     -> /vsis3/{s3_bucket}/{asset_uri}
        azure  -> /vsiaz/{azure_storage_container}/{asset_uri}
        remote -> asset_uri unchanged (already a full URL — STAC import)

    Raises ValueError if asset_uri contains path-traversal or injection
    patterns (WR-01, checked BEFORE VSI prefix construction).
    """
    from app.core.config import settings

    # Remote STAC import: asset_uri is already a full URL — pass through unchanged.
    if asset_uri.startswith("http://") or asset_uri.startswith("https://"):
        return asset_uri

    # WR-01: validate before building any VSI path.
    key = resolve_storage_key(asset_uri, tenant_id=tenant_id)

    provider = settings.storage_provider
    if provider == "s3":
        return f"/vsis3/{settings.s3_bucket}/{key}"
    if provider == "azure":
        return f"/vsiaz/{settings.azure_storage_container}/{key}"
    # local (default): same tenant-prefixed key convention as S3/Azure.
    return f"{settings.upload_staging_dir}/{key}"


def build_titiler_cog_url(
    endpoint: str,
    *,
    query: dict[str, str] | None = None,
    raw_query_suffix: str | None = None,
) -> str:
    """Build a Titiler COG-endpoint URL.

    Args:
        endpoint: Path segment after /cog/ (e.g. "info", "statistics",
            "tiles/WebMercatorQuad/5/10/15.png"). Must not start with "/".
        query: dict of query parameters, URL-encoded. Use for caller-supplied
            user input like `url=...`.
        raw_query_suffix: pre-built query fragment without the leading "?".
            Use for upstream-rendered fragments that already encode their
            values and may repeat keys (e.g. bidx=1&bidx=2 from
            _titiler_render_params).

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

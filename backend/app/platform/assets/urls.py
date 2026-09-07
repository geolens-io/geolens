"""Asset URL resolution with security-aware routing.

Rules:
  - Absolute http(s) hrefs (by-reference origin assets, #1692): passed through
  - Published thumbnails: public URL (no auth, cacheable)
  - S3 + published data assets: presigned URL (time-limited)
  - Local storage, or draft/ready/internal records: no unauthenticated proxy
    URL emitted (GAP-031)

GAP-031: nginx's ``location /assets/`` serves the SPA bundle, not storage
files, so a bare ``/assets/{key}`` URL is dead. Returning ``None`` lets
callers (e.g. ``_build_stac_assets``) omit the asset rather than emit a
broken href.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.platform.storage.provider import StorageProvider


def resolve_asset_url(
    href: str,
    *,
    storage_backend: str,
    record_status: str,
    roles: list[str] | None = None,
    public_api_url: str,
    storage_provider: "StorageProvider | None" = None,
    presign_ttl: int = 3600,
) -> str | None:
    """Resolve an asset href to the correct URL form.

    Returns None when no safe authorized URL exists (e.g. a local-storage
    path that would collide with the SPA /assets/ nginx location — GAP-031).
    """
    # feat(#1692): a by-reference origin asset (STAC import) stores the
    # publisher's already-public absolute URL as its href — not managed
    # storage, so the presign branch and the GAP-031 refusal below would
    # both mishandle it. Checked first and passed through untouched.
    if href.startswith(("http://", "https://")):
        return href

    # S3 + published data assets: signed URL (always safe — signed by provider)
    is_published = record_status == "published"
    if is_published and storage_backend == "s3" and storage_provider is not None:
        from app.platform.storage.titiler_url import resolve_current_storage_key

        key = _extract_storage_key(href)
        physical_key = resolve_current_storage_key(key)
        presign_options = {"expiration": presign_ttl}
        return storage_provider.generate_presigned_get_url(
            physical_key, **presign_options
        )

    # GAP-031: no backend route serves /assets/{key} — nginx returns the SPA
    # index or a 404, never the storage file. Return None so callers omit the
    # asset rather than publish a dead href.
    return None


def _extract_storage_key(href: str) -> str:
    if href.startswith("s3://"):
        # s3://bucket/key -> key
        parts = href.split("/", 3)
        return parts[3] if len(parts) > 3 else ""

    return href.lstrip("/")

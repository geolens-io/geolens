"""Asset URL resolution with security-aware routing.

Rules:
  - Published thumbnails: public URL (no auth, cacheable)
  - S3 + published data assets: presigned URL (time-limited)
  - Local storage: no unauthenticated proxy URL emitted (GAP-031)
  - Draft/ready/internal records: no unauthenticated proxy URL emitted (GAP-031)

GAP-031 — The previous implementation emitted ``/assets/{key}`` for all
local-storage and non-published paths.  That URL has no backend route: the
nginx ``location /assets/`` block serves the SPA bundle directory, not
storage files, so the URL was both dead and a potential collision surface.
Because ``dataset_assets`` is never populated (BUG-041, Tier-2), this change
has no live output impact.  Returning ``None`` for the unsafe proxy path lets
callers (e.g. ``_build_stac_assets``) omit the asset entry rather than emit a
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

    Args:
        href: Raw asset path (storage-relative or absolute).
        storage_backend: "local" or "s3".
        record_status: Current publication status of the record.
        roles: STAC asset roles (e.g., ["data"], ["thumbnail"]).
        public_api_url: Base URL for proxy endpoints.
        storage_provider: Storage provider instance for signing.
        presign_ttl: Presigned URL TTL in seconds (default 3600).

    Returns:
        Resolved URL string, or None when no safe authorized URL exists
        (e.g. local-storage paths that would collide with the SPA /assets/
        nginx location — GAP-031).
    """
    # S3 + published data assets: signed URL (always safe — signed by provider)
    is_published = record_status == "published"
    if is_published and storage_backend == "s3" and storage_provider is not None:
        key = _extract_storage_key(href)
        return storage_provider.generate_presigned_get_url(key, expiration=presign_ttl)

    # GAP-031: Do NOT emit a bare /assets/{key} proxy URL.  No backend route
    # exists for that path; nginx serves the SPA bundle at /assets/ and would
    # return the SPA index or a 404 — never the storage file.  Return None so
    # callers can omit the asset entry rather than publish a dead href.
    # This covers: local storage (any status), non-S3, and S3 without a
    # signed-URL provider.
    return None


def _extract_storage_key(href: str) -> str:
    """Extract the storage key from an href.

    Handles both absolute paths (/data/uploads/...) and S3 keys (uploads/...).
    Strips leading slash and common prefixes.
    """
    # If it's an S3 URI, extract the key portion
    if href.startswith("s3://"):
        # s3://bucket/key -> key
        parts = href.split("/", 3)
        return parts[3] if len(parts) > 3 else ""

    # Strip leading slash for consistency
    return href.lstrip("/")

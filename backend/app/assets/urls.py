"""Asset URL resolution with security-aware routing.

Rules:
  - Published thumbnails: public URL (no auth, cacheable)
  - S3 + published data assets: presigned URL (time-limited)
  - Local storage: always proxy through API
  - Draft/ready/internal records: always proxy regardless of storage
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.storage.provider import StorageProvider


def resolve_asset_url(
    href: str,
    *,
    storage_backend: str,
    record_status: str,
    roles: list[str] | None = None,
    public_api_url: str,
    storage_provider: "StorageProvider | None" = None,
    presign_ttl: int = 3600,
) -> str:
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
        Resolved URL string.
    """
    is_thumbnail = roles is not None and "thumbnail" in roles
    is_published = record_status == "published"

    # Non-published records: always proxy
    if not is_published:
        return _proxy_url(href, public_api_url)

    # Published thumbnails: public URL (no auth required)
    if is_thumbnail:
        return _proxy_url(href, public_api_url)

    # S3 + published data assets: signed URL
    if storage_backend == "s3" and storage_provider is not None:
        key = _extract_storage_key(href)
        return storage_provider.generate_presigned_get_url(key, expiration=presign_ttl)

    # Fallback: proxy through API
    return _proxy_url(href, public_api_url)


def _proxy_url(href: str, public_api_url: str) -> str:
    """Build a proxy URL through the API."""
    key = _extract_storage_key(href)
    base = public_api_url.rstrip("/") if public_api_url else ""
    path = f"/assets/{key}"
    return f"{base}{path}"


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

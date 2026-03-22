from fastapi import Request

from app.public_urls import get_env_public_api_url, join_public_url


def build_url(
    path: str,
    request: Request | None = None,
    *,
    base_url: str | None = None,
) -> str:
    """Build an absolute API URL for OGC and distribution links."""
    resolved_base = base_url or get_env_public_api_url(request=request)
    return join_public_url(resolved_base, path)

"""Derive GDAL's AWS_* config for its S3 VSI reads from the app's S3_* settings.

fix(#579): with STORAGE_PROVIDER=s3 on an S3-compatible endpoint (MinIO, R2),
GDAL S3 VSI reads targeted the default AWS endpoint and failed, since only the
application-side SDK honored S3_ENDPOINT/S3_ADDRESSING_STYLE, not GDAL.

`configure_gdal_s3_env()` runs once at api/worker start, before any
GDAL/rasterio use, applying values via `os.environ.setdefault` so explicit
operator AWS_* env always wins; GDAL subprocesses inherit them through
`os.environ`. Copies no secret not already in the process env.

The titiler container is a separate process tree and cannot be configured
here — compose derives the same trio in its command wrapper, and the Helm
chart derives it at template time.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


def derive_gdal_s3_env(settings: "Settings") -> dict[str, str]:
    """Return the AWS_* variables GDAL needs for its S3 VSI reads.

    Empty when the storage provider is not s3. Endpoint-specific keys
    (AWS_S3_ENDPOINT, AWS_HTTPS) appear only for a custom S3_ENDPOINT;
    AWS_VIRTUAL_HOSTING=FALSE only for path-style addressing (MinIO default).
    """
    if settings.storage_provider != "s3":
        return {}

    derived: dict[str, str] = {}
    if settings.s3_access_key_id:
        derived["AWS_ACCESS_KEY_ID"] = settings.s3_access_key_id
    if settings.s3_secret_access_key:
        derived["AWS_SECRET_ACCESS_KEY"] = (
            settings.s3_secret_access_key.get_secret_value()
        )
    if settings.s3_region:
        derived["AWS_DEFAULT_REGION"] = settings.s3_region

    endpoint = (settings.s3_endpoint or "").strip()
    if endpoint:
        # GDAL wants a scheme-less host[:port]; the scheme maps to AWS_HTTPS.
        # (GDAL >= 3.5.2 would accept a full URL, but the scheme-less form
        # works on every GDAL the images ship.) Scheme resolution mirrors
        # S3StorageProvider: an explicit scheme wins; a scheme-less endpoint
        # is http exactly when S3_ALLOW_HTTP is set.
        scheme, sep, rest = endpoint.partition("://")
        host = rest if sep else endpoint
        host = host.split("/", 1)[0]
        if host:
            derived["AWS_S3_ENDPOINT"] = host
            uses_http = scheme == "http" if sep else settings.s3_allow_http
            if uses_http:
                derived["AWS_HTTPS"] = "NO"

    if settings.s3_addressing_style == "path":
        derived["AWS_VIRTUAL_HOSTING"] = "FALSE"

    return derived


def configure_gdal_s3_env(settings: "Settings") -> None:
    """Apply the derived GDAL S3 config to the process environment.

    setdefault semantics: an operator who already exports AWS_* env (or relies
    on ambient AWS credentials with no custom endpoint) is left untouched.
    """
    for key, value in derive_gdal_s3_env(settings).items():
        os.environ.setdefault(key, value)

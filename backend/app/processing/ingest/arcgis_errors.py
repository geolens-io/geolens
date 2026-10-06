"""The error an ArcGIS service answered a failed import query with."""

import asyncio
import json
import re
import unicodedata

import structlog

from app.core.url_redaction import (
    REDACTED_SECRET,
    redact_url_credentials,
    scrub_registered_credentials,
    scrub_secret_value,
)
from app.platform.probe_bounds import bounded_probe_read
from app.platform.security import make_safe_client
from app.platform.service_endpoints import DEFAULT_CHECK_TIMEOUT, OGC_JSON_ACCEPT

# GDAL reads an ArcGIS error envelope as a broken feature collection and drops
# the body of an HTTP error, so the service's own message never reaches stderr.
ARCGIS_ERROR_RESPONSE_RE = re.compile(
    r"Missing 'features' member|Failed to read (?:ESRIJSON|GeoJSON) data"
    r"|HTTP error code : [45]\d\d"
)

MAX_DETAIL_CHARS = 300
_MAX_DETAILS = 5

# A credential header the service quotes back, whatever token it carries.
_CREDENTIAL_HEADER_ECHO_RE = re.compile(
    r"(?i)\b((?:x-esri-|proxy-)?authorization)\s*[:=]\s*"
    r"(?:(?:bearer|basic)\s+)?[^\s,;]+"
)


def _one_line(text: str) -> str:
    """``text`` with control, format and separator characters as single spaces."""
    return " ".join(
        "".join(
            " " if unicodedata.category(ch)[0] in "CZ" else ch for ch in text
        ).split()
    )


def arcgis_error_detail(data: object, token: str | None) -> str | None:
    """An ArcGIS error envelope's code and message, redacted and bounded.

    None when ``data`` is not an envelope with a message.
    """
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None
    parts = [error.get("message")]
    details = error.get("details")
    if isinstance(details, list):
        parts.extend(details[:_MAX_DETAILS])
    texts: list[str] = []
    for part in parts:
        if isinstance(part, str) and (text := _one_line(part)) and text not in texts:
            texts.append(text)
    if not texts:
        return None
    text = scrub_registered_credentials(scrub_secret_value(" ".join(texts), token))
    text = _CREDENTIAL_HEADER_ECHO_RE.sub(
        rf"\1: {REDACTED_SECRET}", redact_url_credentials(text)
    )
    code = error.get("code")
    if isinstance(code, int) and not isinstance(code, bool) and 0 <= code < 10_000:
        detail = f"ArcGIS error {code}: {text}"
    else:
        detail = f"ArcGIS error: {text}"
    if len(detail) <= MAX_DETAIL_CHARS:
        return detail
    return detail[: MAX_DETAIL_CHARS - 3].rstrip() + "..."


async def fetch_arcgis_error_detail(gdal_source: str, token: str | None) -> str | None:
    """Re-send the query a GDAL ArcGIS fetch failed on and return its error.

    The request is the one GDAL sent, token included, so the service answers
    it the same way. None when the answer is no error envelope or can't be read.
    """
    _, _, url = gdal_source.partition(":")
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            async with make_safe_client(timeout=DEFAULT_CHECK_TIMEOUT) as client:
                body, _ = await bounded_probe_read(
                    client,
                    url,
                    headers={},
                    accept=OGC_JSON_ACCEPT,
                    raise_for_status=False,
                )
        data = json.loads(body)
    except Exception as exc:  # broad: a diagnostic read; the import already failed
        structlog.get_logger().warning(
            "arcgis_error_detail_unavailable", error_class=type(exc).__name__
        )
        return None
    return arcgis_error_detail(data, token)

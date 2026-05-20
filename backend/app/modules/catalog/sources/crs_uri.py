"""CRS URI/URN → EPSG integer parser.

Phase 1057 CRS-06 (D-07, D-13):
  Converts four standardised URI/URN CRS reference forms emitted by GeoServer and
  pygeoapi into EPSG integer codes.  Anything unrecognised returns None so callers
  preserve today's null-CRS fallthrough behaviour (D-07 default-deny).

Covered forms (D-07 — do NOT add forms not on this list):
  1. http://www.opengis.net/def/crs/OGC/1.3/CRS84  → 4326
  2. https://www.opengis.net/def/crs/OGC/1.3/CRS84 → 4326  (HTTPS variant of 1)
  3. http(s)://www.opengis.net/def/crs/EPSG/0/{N}  → {N}
  4. urn:ogc:def:crs:EPSG::{N}                     → {N}
  5. urn:ogc:def:crs:OGC:1.3:CRS84                 → 4326

NOT covered (handled elsewhere in the ingest pipeline):
  - Bare "EPSG:N" strings — handled by ogrinfo projjson / WKT extraction
  - Backend-side reprojection — explicitly out of scope per D-13

Trust / threat model (T-1057C-01):
  All patterns are compiled with anchored ^…$ regexes and a known-form allowlist.
  Unrecognised URIs return None (default-deny).  No eval, no SQL, no path
  manipulation.  The function signature is ``str | None → int | None``.
"""

from __future__ import annotations

import re

# ── Compiled regex constants (module-level: compiled once, never recompiled) ──

# Forms 1 + 2: OGC CRS84 via HTTP or HTTPS.
# Trailing slash is optional; case-sensitive by design (OGC URIs are case-sensitive).
_RE_OGC_CRS84_HTTP = re.compile(
    r"^https?://www\.opengis\.net/def/crs/OGC/1\.3/CRS84/?$"
)

# Form 3: EPSG code via HTTP or HTTPS numeric path segment.
# Captures the numeric code; rejects non-numeric codes at match time (\d+).
_RE_EPSG_HTTP = re.compile(
    r"^https?://www\.opengis\.net/def/crs/EPSG/0/(\d+)/?$"
)

# Form 4: EPSG URN (WFS 2.0 DefaultCRS and OGC API storageCrs).
_RE_EPSG_URN = re.compile(r"^urn:ogc:def:crs:EPSG::(\d+)$")

# Form 5: OGC CRS84 URN.
_RE_OGC_CRS84_URN = re.compile(r"^urn:ogc:def:crs:OGC:1\.3:CRS84$")


def parse_crs_uri(value: str | None) -> int | None:
    """Map a URI/URN-form CRS reference to an EPSG integer code.

    Recognises exactly the four D-07 forms listed in the module docstring.
    Returns ``None`` for any input that does not pattern-match (default-deny).

    Args:
        value: A CRS URI or URN string, or ``None`` / empty string.

    Returns:
        EPSG integer code (e.g. 4326, 3857, 32633), or ``None``.

    Examples::

        >>> parse_crs_uri("http://www.opengis.net/def/crs/OGC/1.3/CRS84")
        4326
        >>> parse_crs_uri("urn:ogc:def:crs:EPSG::32633")
        32633
        >>> parse_crs_uri("EPSG:4326")   # bare EPSG strings → None (not this helper's job)
        None
        >>> parse_crs_uri(None)
        None

    EPSG integer codes are accepted without an artificial upper bound.
    The EPSG authority controls the namespace; downstream PostGIS rejects
    unknown SRIDs at Find_SRID / ST_Transform time (T-1057C-04 accepted).
    """
    if not value:
        return None

    # Form 1 + 2: OGC CRS84 HTTP/HTTPS → 4326
    if _RE_OGC_CRS84_HTTP.match(value):
        return 4326

    # Form 3: EPSG via HTTP/HTTPS numeric path segment → {N}
    m = _RE_EPSG_HTTP.match(value)
    if m:
        return int(m.group(1))

    # Form 4: EPSG URN → {N}
    m = _RE_EPSG_URN.match(value)
    if m:
        return int(m.group(1))

    # Form 5: OGC CRS84 URN → 4326
    if _RE_OGC_CRS84_URN.match(value):
        return 4326

    # Unrecognised — preserve null-CRS fallthrough (D-07 default-deny)
    return None

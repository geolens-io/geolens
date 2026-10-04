# SPDX-License-Identifier: Apache-2.0
"""Read-only inventory of an ArcGIS Online or Portal for ArcGIS organization.

Hand-maintained. Every request goes to the portal named on the command line
and nowhere else: not to GeoLens, and not to the services an item points at.
Nothing on the portal is changed. The token and password live in memory for
one run and are never written anywhere.
"""

from __future__ import annotations

import getpass
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlencode, urlsplit

from . import arcgis_report as _report
from . import output as _output
from ._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_SERVER,
    EXIT_USAGE,
)

# AGOL and Enterprise 10.5.1+ read the token from this header. Not
# `Authorization`, which a web tier in front of Enterprise may consume.
ESRI_AUTHORIZATION_HEADER = "X-Esri-Authorization"
DEFAULT_PORTAL_URL = "https://www.arcgis.com"
PAGE_SIZE = 100
DEFAULT_MAX_ITEMS = 10_000
MAX_CONCURRENCY = 4
# ArcGIS search pages through only the first 10,000 results of a query.
SEARCH_RESULT_CEILING = 10_000
MIN_REQUEST_INTERVAL = 0.1
SOCKET_TIMEOUT = 10.0
REQUEST_DEADLINE = 30.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
GET_ATTEMPTS = 3
MAX_RETRY_AFTER = 60.0
TOKEN_EXPIRATION_MINUTES = 60

_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
_TOKEN_REQUIRED = 499
_TOKEN_INVALID = 498
_TOKEN_CHARS = re.compile(r"[\x21-\x7e]+")
_CREDENTIAL_PARAM = re.compile(r"((?:token|password)=)[^&\s\"']+", re.IGNORECASE)
_ARCGIS_ONLINE_HOSTED = re.compile(r"(services|tiles)\d*\.arcgis\.com")

SUPPORTED = "supported"
PARTIAL = "partial"
UNSUPPORTED = "unsupported"
CLASSES = (SUPPORTED, PARTIAL, UNSUPPORTED)

_NO_APP_EQUIVALENT = (UNSUPPORTED, "no_equivalent_app")
_NOT_CATALOG_DATA = (UNSUPPORTED, "not_catalog_data")
_OGC_REFERENCE = (PARTIAL, "ogc_service_reference")
_DATA_FILE = (PARTIAL, "data_file_import_candidate")

# Item `type` -> (class, reason). `classify` refines Feature Service, Map
# Service and Web Mapping Application by typeKeywords.
ITEM_TYPE_CLASSES: dict[str, tuple[str, str]] = {
    "Feature Service": (SUPPORTED, "hosted_feature_layer"),
    "Map Service": (SUPPORTED, "map_service_layer_import"),
    "Web Map": (PARTIAL, "web_map_styling_needs_translation"),
    "Image Service": (UNSUPPORTED, "no_import_path"),
    "Vector Tile Service": (UNSUPPORTED, "no_import_path"),
    "Scene Service": (UNSUPPORTED, "no_scene_import"),
    "Web Scene": (UNSUPPORTED, "no_scene_import"),
    "3DTilesService": (UNSUPPORTED, "no_scene_import"),
    "WMS": _OGC_REFERENCE,
    "WFS": _OGC_REFERENCE,
    "WMTS": _OGC_REFERENCE,
    "WCS": _OGC_REFERENCE,
    "KML": _OGC_REFERENCE,
    "OGCFeatureServer": _OGC_REFERENCE,
    "Feature Collection": _DATA_FILE,
    "CSV": _DATA_FILE,
    "Shapefile": _DATA_FILE,
    "GeoJson": _DATA_FILE,
    "File Geodatabase": _DATA_FILE,
    "Web Mapping Application": _NO_APP_EQUIVALENT,
    "Web Experience": _NO_APP_EQUIVALENT,
    "Dashboard": _NO_APP_EQUIVALENT,
    "StoryMap": _NO_APP_EQUIVALENT,
    "Hub Site Application": _NO_APP_EQUIVALENT,
    "Hub Page": _NO_APP_EQUIVALENT,
    "Hub Initiative": _NO_APP_EQUIVALENT,
    "Form": _NO_APP_EQUIVALENT,
    "Workforce Project": _NO_APP_EQUIVALENT,
    "Mission": _NO_APP_EQUIVALENT,
    "Notebook": _NO_APP_EQUIVALENT,
    "Solution": _NO_APP_EQUIVALENT,
    "Data Pipeline": _NO_APP_EQUIVALENT,
    "Investigation": _NO_APP_EQUIVALENT,
    "Knowledge Studio Project": _NO_APP_EQUIVALENT,
    "GeoBIM Project": _NO_APP_EQUIVALENT,
    "Urban Model": _NO_APP_EQUIVALENT,
    "Native Application": _NO_APP_EQUIVALENT,
    "Geocoding Service": _NOT_CATALOG_DATA,
    "Geometry Service": _NOT_CATALOG_DATA,
    "Geoprocessing Service": _NOT_CATALOG_DATA,
    "Network Analysis Service": _NOT_CATALOG_DATA,
    "Workflow Manager Service": _NOT_CATALOG_DATA,
    "Pro Map": _NOT_CATALOG_DATA,
    "Map Area": _NOT_CATALOG_DATA,
    "Layer Package": _NOT_CATALOG_DATA,
    "Map Package": _NOT_CATALOG_DATA,
    "Code Attachment": _NOT_CATALOG_DATA,
}

# Only cite a dated Esri page here; an undated retirement gets "date": None.
RETIREMENTS: dict[str, dict[str, str | None]] = {
    "web_appbuilder": {
        "label": "Web AppBuilder",
        "status": "retiring",
        "date": "2027-Q2",
        "note": (
            "ArcGIS Online: no new apps from Q1 2026, no updates to existing "
            "apps from Q4 2026, apps stop working in Q2 2027. ArcGIS Enterprise "
            "11.5 is the last release that includes it."
        ),
        "source_url": "https://doc.arcgis.com/en/web-appbuilder/latest/create-apps/wab-retirement.htm",
    },
    "classic_story_maps": {
        "label": "Classic Esri Story Maps",
        "status": "retired",
        "date": "2026-Q1",
        "note": "Retired from ArcGIS Online in Q1 2026.",
        "source_url": "https://www.esri.com/en-us/arcgis/products/arcgis-storymaps/classic",
    },
}

_SERVICE_TYPES = frozenset(
    {
        "Feature Service",
        "Map Service",
        "Image Service",
        "Vector Tile Service",
        "Scene Service",
    }
)
_APP_DATA_TYPES = frozenset({"Web Mapping Application", "Web Experience", "Dashboard"})
_WEB_MAP_TYPE = "Web Map"
_WAB_KEYWORDS = frozenset({"web appbuilder", "wab2d", "wab3d"})


class Redactor:
    """Replaces known secrets, and any ``token=``/``password=`` value, in text."""

    def __init__(self) -> None:
        self._forms: list[str] = []

    def add(self, secret: str | None) -> None:
        if not secret:
            return
        for form in (secret, quote(secret, safe=""), quote_plus(secret)):
            if form not in self._forms:
                self._forms.append(form)
        self._forms.sort(key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for form in self._forms:
            text = text.replace(form, "[REDACTED]")
        return _CREDENTIAL_PARAM.sub(r"\1[REDACTED]", text)


class PortalError(Exception):
    """A portal request failed; ``kind`` picks the exit code.

    The message is redacted when the error is built, so ``str()`` is safe to
    print anywhere.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        http_status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_opener() -> urllib.request.OpenerDirector:
    """An opener that turns every redirect into an HTTPError.

    A redirect would carry the credential header to wherever the portal
    points, so none is followed.
    """
    return urllib.request.build_opener(_RefuseRedirects())


class PortalClient:
    """JSON reads against one portal's ``/sharing/rest`` API."""

    def __init__(
        self,
        root_url: str,
        *,
        opener: Any,
        redact: Redactor,
        token: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        on_request: Callable[[str, str], None] | None = None,
    ) -> None:
        self.root = root_url.rstrip("/")
        self.token = token
        self._opener = opener
        self._redact = redact
        self._sleep = sleep
        self._clock = clock
        self._on_request = on_request
        self._form_token = False
        self._referer: str | None = None
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def _error(self, message: str, **kwargs: Any) -> PortalError:
        return PortalError(self._redact(message), **kwargs)

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> dict:
        """GET ``/sharing/rest/<path>`` as JSON, retrying transient failures.

        An error envelope in a 200 body raises ``PortalError``. A 499 "token
        required" with the header present means a pre-10.5.1 server ignored
        it; from then on the token goes in a POST form field, never the URL.
        """
        query = {**(params or {}), "f": "json"}
        url = f"{self.root}/sharing/rest/{path}"
        data = self._read(url, query)
        code = _envelope_code(data)
        if code == _TOKEN_REQUIRED and self.token and not self._form_token:
            self._form_token = True
            data = self._read(url, query)
            code = _envelope_code(data)
        if code is not None:
            raise self._envelope_error(path, data, code)
        return data

    def generate_token(self, username: str, password: str) -> str:
        """Mint a 60-minute token bound to the portal origin as its referer.

        Never retried: ArcGIS locks an account after five failed sign-ins in
        fifteen minutes. Every later request sends that referer, since a
        portal enforcing the binding rejects the token without it.
        """
        referer = _origin(self.root)
        fields = {
            "username": username,
            "password": password,
            "client": "referer",
            "referer": referer,
            "expiration": str(TOKEN_EXPIRATION_MINUTES),
            "f": "json",
        }
        url = f"{self.root}/sharing/rest/generateToken"
        try:
            data = self._exchange("POST", url, fields, {}, attempts=1)
        except PortalError as exc:
            if exc.kind != "auth":
                raise
            data = {}
        token = data.get("token")
        if _envelope_code(data) is not None or not isinstance(token, str) or not token:
            detail = _envelope_message(data, self._redact) or "no token in the response"
            raise self._error(
                f"sign-in failed: {detail}. Accounts that sign in through SAML "
                "or OpenID Connect cannot use a password here; pass a token "
                "with --token, ARCGIS_TOKEN or --token-stdin instead.",
                kind="auth",
            )
        if not _TOKEN_CHARS.fullmatch(token):
            raise self._error(
                "the portal returned a token with unexpected characters",
                kind="auth",
            )
        self._redact.add(token)
        self.token = token
        self._referer = referer
        return token

    def _read(self, url: str, query: dict[str, Any]) -> dict:
        headers = {"Referer": self._referer} if self._referer else {}
        if self.token and self._form_token:
            return self._exchange(
                "POST",
                url,
                {**query, "token": self.token},
                headers,
                attempts=GET_ATTEMPTS,
            )
        if self.token:
            headers[ESRI_AUTHORIZATION_HEADER] = f"Bearer {self.token}"
        return self._exchange(
            "GET", f"{url}?{urlencode(query)}", None, headers, attempts=GET_ATTEMPTS
        )

    def _exchange(
        self,
        method: str,
        url: str,
        form: Mapping[str, Any] | None,
        headers: dict[str, str],
        *,
        attempts: int,
    ) -> dict:
        body = urlencode(form).encode() if form is not None else None
        if body is not None:
            headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
        path = urlsplit(url).path
        for attempt in range(1, attempts + 1):
            self._wait_turn()
            if self._on_request:
                self._on_request(method, path)
            request = urllib.request.Request(
                url,
                data=body,
                headers={**headers, "Accept": "application/json"},
                method=method,
            )
            try:
                raw = self._open_once(request, path)
            except PortalError as exc:
                if not exc.retryable or attempt == attempts:
                    raise
                delay = exc.retry_after
                self._sleep(delay if delay is not None else 0.5 * 2 ** (attempt - 1))
                continue
            return self._parse(raw, path)
        raise AssertionError("unreachable")

    def _wait_turn(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + MIN_REQUEST_INTERVAL
        if wait > 0:
            self._sleep(wait)

    def _open_once(self, request: urllib.request.Request, path: str) -> bytes:
        deadline = self._clock() + REQUEST_DEADLINE
        try:
            with self._opener.open(request, timeout=SOCKET_TIMEOUT) as response:
                return self._read_capped(response, path, deadline)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if 300 <= status < 400:
                raise self._error(
                    f"{path} answered with a redirect (HTTP {status}). Redirects "
                    "are refused so the credential stays on the portal origin; "
                    "pass the final portal URL with --portal-url.",
                    kind="redirect",
                    http_status=status,
                ) from None
            kind = "auth" if status == 401 else "server" if status >= 500 else "refused"
            raise self._error(
                f"HTTP {status} from {path}",
                kind=kind,
                http_status=status,
                retryable=status in _RETRYABLE_STATUSES,
                retry_after=_retry_after(exc.headers),
            ) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise self._error(
                f"network error on {path}: {reason}", kind="network", retryable=True
            ) from None

    def _read_capped(self, response: Any, path: str, deadline: float) -> bytes:
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            raise self._too_large(path)
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise self._error(
                    f"{path} took longer than {REQUEST_DEADLINE:.0f} s",
                    kind="network",
                    retryable=True,
                )
            _limit_socket_wait(response, remaining)
            # read1 returns after one socket read; read(n) would keep reading
            # until n bytes arrive, so a trickling server never hit the check.
            chunk = response.read1(64 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise self._too_large(path)
            chunks.append(chunk)

    def _too_large(self, path: str) -> PortalError:
        return self._error(
            f"{path} is larger than {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB",
            kind="invalid",
        )

    def _parse(self, raw: bytes, path: str) -> dict:
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            raise self._error(f"{path} did not return JSON", kind="invalid") from None
        if not isinstance(data, dict):
            raise self._error(f"{path} did not return a JSON object", kind="invalid")
        return data

    def _envelope_error(self, path: str, data: dict, code: int) -> PortalError:
        message = _envelope_message(data, self._redact) or "no message"
        if code in (_TOKEN_INVALID, _TOKEN_REQUIRED):
            kind = "auth"
        elif code >= 500:
            kind = "server"
        else:
            kind = "refused"
        return self._error(
            f"{path} returned error {code}: {message}", kind=kind, http_status=code
        )


def _envelope_code(data: Mapping[str, Any]) -> int | None:
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) and not isinstance(code, bool) else 0


def _envelope_message(data: Mapping[str, Any], redact: Redactor) -> str:
    """The envelope's message and details, redacted and then shortened.

    Redacting first matters: a cut through a secret leaves a prefix that no
    longer matches it.
    """
    error = data.get("error")
    if not isinstance(error, dict):
        return ""
    parts = [str(error.get("message") or "")]
    details = error.get("details")
    if isinstance(details, list):
        parts.extend(str(d) for d in details if d)
    return redact(" ".join(p for p in parts if p))[:500]


def _limit_socket_wait(response: Any, seconds: float) -> None:
    """Cap the next blocking socket read at *seconds*.

    http.client exposes no public handle on the socket, so this reaches
    through the buffered reader and does nothing when the shape differs.
    """
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if sock is not None:
        sock.settimeout(min(SOCKET_TIMEOUT, max(seconds, 0.001)))


def _retry_after(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if value and value.strip().isdigit():
        return min(float(value.strip()), MAX_RETRY_AFTER)
    return None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def sanitize_url(url: Any) -> str | None:
    """Scheme, host and path only: a stored service URL can carry a token in
    its query string or credentials in its userinfo."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parts.scheme}://{netloc}{parts.path}"


def classify(item: Mapping[str, Any]) -> dict[str, Any]:
    """Class, reason, retirement and hosted flag for one portal item."""
    item_type = str(item.get("type") or "")
    keywords = {str(k).lower() for k in item.get("typeKeywords") or []}
    hosted_service = "hosted service" in keywords
    retirement: str | None = None
    klass, reason = ITEM_TYPE_CLASSES.get(item_type, (UNSUPPORTED, "unknown_type"))
    if item_type == "Feature Service":
        if "view service" in keywords:
            reason = "hosted_feature_view"
        elif not hosted_service:
            reason = "non_hosted_service_reachability_external"
    elif item_type == "Map Service" and hosted_service:
        klass, reason = PARTIAL, "hosted_tile_layer_cached_only"
    elif item_type == "Web Mapping Application":
        if any("story map" in k for k in keywords):
            reason, retirement = "classic_story_map", "classic_story_maps"
        elif keywords & _WAB_KEYWORDS:
            reason, retirement = "web_appbuilder_app", "web_appbuilder"
    return {
        "class": klass,
        "reason": reason,
        "retirement": retirement,
        "hosted": hosted_service if item_type in _SERVICE_TYPES else None,
    }


def _iso_from_ms(value: Any) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    try:
        stamp = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return stamp.isoformat().replace("+00:00", "Z")


def _item_row(item: Mapping[str, Any]) -> dict[str, Any]:
    verdict = classify(item)
    retirement_id = verdict["retirement"]
    retirement = None
    if retirement_id:
        known = RETIREMENTS[retirement_id]
        retirement = {
            "id": retirement_id,
            "status": known["status"],
            "date": known["date"],
        }
    size = item.get("size")
    item_type = str(item.get("type") or "")
    if item_type == _WEB_MAP_TYPE or item_type in _APP_DATA_TYPES:
        dependencies_status = "pending"
    else:
        dependencies_status = "not_applicable"
    return {
        "id": str(item.get("id") or ""),
        "type": item_type,
        "type_keywords": [str(k) for k in item.get("typeKeywords") or []],
        "title": str(item.get("title") or ""),
        "owner": str(item.get("owner") or ""),
        "sharing": {"access": str(item.get("access") or "private"), "groups": None},
        "size_bytes": size
        if isinstance(size, int) and not isinstance(size, bool) and size >= 0
        else None,
        "created": _iso_from_ms(item.get("created")),
        "modified": _iso_from_ms(item.get("modified")),
        "url": sanitize_url(item.get("url")),
        "class": verdict["class"],
        "reason": verdict["reason"],
        "retirement": retirement,
        "hosted": verdict["hosted"],
        "dependencies_status": dependencies_status,
    }


@dataclass
class Inventory:
    portal: dict[str, Any]
    auth: dict[str, Any]
    scope: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    search_ceiling: bool = False
    abort: PortalError | None = None


def _pages(
    client: PortalClient, path: str, params: dict[str, Any], key: str
) -> Iterator[tuple[list[Any], dict]]:
    start = 1
    while True:
        page = client.get_json(path, {**params, "num": PAGE_SIZE, "start": start})
        rows = page.get(key)
        next_start = page.get("nextStart")
        if not isinstance(rows, list):
            raise PortalError(
                f"{path} returned no '{key}' list at start={start}", kind="invalid"
            )
        if (
            not isinstance(next_start, int)
            or isinstance(next_start, bool)
            or (next_start != -1 and next_start <= start)
        ):
            raise PortalError(
                f"{path} returned no usable 'nextStart' at start={start}",
                kind="invalid",
            )
        yield rows, page
        if next_start == -1:
            return
        start = next_start


def _has_next(page: Mapping[str, Any]) -> bool:
    next_start = page.get("nextStart")
    return isinstance(next_start, int) and next_start > 0


def _at_search_ceiling(page: Mapping[str, Any], rows: list[Any]) -> bool:
    """Whether a search page reaches the server's result ceiling.

    At the ceiling the last page still says ``nextStart: -1`` and ``total``
    is capped, so neither proves the listing is complete.
    """
    total, start = page.get("total"), page.get("start")
    if isinstance(total, int) and total >= SEARCH_RESULT_CEILING:
        return True
    return isinstance(start, int) and start + len(rows) - 1 >= SEARCH_RESULT_CEILING


def _list_items(
    client: PortalClient, inv: Inventory, max_items: int
) -> Iterator[dict[str, Any]]:
    """Raw items for the scope, deduplicated, stopping at *max_items*.

    User scope reads the root folder first; its ``folders`` list names the
    other folders to page through.
    """
    if inv.scope["mode"] == "org":
        org_query = {
            "q": f"orgid:{inv.scope['org_id']}",
            "sortField": "modified",
            "sortOrder": "desc",
        }
        listings = [("search", org_query, "results")]
    else:
        user_path = f"content/users/{quote(inv.scope['owner'], safe='')}"
        listings = [(user_path, {}, "items")]
    seen: set[str] = set()
    position = 0
    while position < len(listings):
        path, params, key = listings[position]
        position += 1
        for rows, page in _pages(client, path, params, key):
            if path == "search" and _at_search_ceiling(page, rows):
                inv.search_ceiling = True
            folders = page.get("folders")
            if inv.scope["mode"] == "user" and len(listings) == 1:
                if isinstance(folders, list):
                    listings.extend(
                        (f"{path}/{quote(str(f['id']), safe='')}", {}, "items")
                        for f in folders
                        if isinstance(f, dict) and f.get("id")
                    )
            for raw in rows:
                if not isinstance(raw, dict) or not raw.get("id"):
                    continue
                if str(raw["id"]) in seen:
                    continue
                if len(seen) >= max_items:
                    inv.truncated = True
                    return
                seen.add(str(raw["id"]))
                yield raw
            if len(seen) >= max_items and (_has_next(page) or position < len(listings)):
                inv.truncated = True
                return


def _hosted_by_url(url: str | None, portal: Mapping[str, Any]) -> bool | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    portal_host = (urlsplit(portal["url"]).hostname or "").lower()
    if portal["kind"] == "online":
        return bool(_ARCGIS_ONLINE_HOSTED.fullmatch(host))
    return host == portal_host and "/hosted/" in parts.path.lower()


def _dependency(
    from_id: str,
    to_id: Any,
    raw_url: Any,
    *,
    role: str,
    layer_type: Any,
    layer_id: Any,
    title: Any,
    order: int,
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> dict[str, Any]:
    to_id = str(to_id) if isinstance(to_id, str) and to_id else None
    url = sanitize_url(raw_url)
    target = index.get(to_id) if to_id else None
    return {
        "from_id": from_id,
        "to_id": to_id,
        "to_url": url,
        "role": role,
        "layer_type": str(layer_type) if layer_type else None,
        "layer_id": str(layer_id) if layer_id is not None else None,
        "title": str(title) if title else None,
        "order": order,
        "hosted": target["hosted"] if target else _hosted_by_url(url, portal),
        "resolved": target is not None,
    }


def web_map_dependencies(
    item_id: str,
    data: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Layer, basemap and table references of one web map, in map order."""
    rows: list[dict[str, Any]] = []

    def walk(layers: Any, role: str) -> None:
        if not isinstance(layers, list):
            return
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            if layer.get("layerType") == "GroupLayer" and isinstance(
                layer.get("layers"), list
            ):
                walk(layer["layers"], role)
                continue
            rows.append(
                _dependency(
                    item_id,
                    layer.get("itemId"),
                    layer.get("url") or layer.get("styleUrl"),
                    role=role,
                    layer_type=layer.get("layerType"),
                    layer_id=layer.get("id"),
                    title=layer.get("title"),
                    order=len(rows),
                    index=index,
                    portal=portal,
                )
            )

    walk(data.get("operationalLayers"), "operational_layer")
    basemap = data.get("baseMap")
    if isinstance(basemap, dict):
        walk(basemap.get("baseMapLayers"), "basemap")
    walk(data.get("tables"), "table")
    return rows


_APP_MAP_SOURCE_TYPES = frozenset({"WEB_MAP", "WEB_SCENE"})


def _app_references(
    data: Mapping[str, Any],
) -> list[tuple[str, str, str, str | None]] | None:
    """(item id, kind, role, layer id) from the documented app config keys, or
    None if none of those keys is present.

    Maps an app opens are ``app_web_map``; layers it reads directly, such as a
    dashboard chart's dataset or an Experience Builder feature layer source,
    are ``app_data_source`` with their layer id.
    """
    found: list[tuple[str, str, str, str | None]] = []
    recognized = False

    def add(ref: Any, kind: Any, role: str, layer_id: Any = None) -> None:
        if isinstance(ref, str) and ref:
            layer = (
                None
                if layer_id is None or isinstance(layer_id, bool)
                else str(layer_id)
            )
            found.append((ref, str(kind or ""), role, layer))

    values = data.get("values")
    if isinstance(values, dict) and "webmap" in values:
        recognized = True
        webmaps = values["webmap"]
        for ref in webmaps if isinstance(webmaps, list) else [webmaps]:
            add(ref, "webmap", "app_web_map")
    app_map = data.get("map")
    if isinstance(app_map, dict) and "itemId" in app_map:
        recognized = True
        add(app_map["itemId"], "webmap", "app_web_map")
    sources = data.get("dataSources")
    nested = data.get("dataSource")
    if not isinstance(sources, dict) and isinstance(nested, dict):
        sources = nested.get("dataSources")
    if isinstance(sources, dict):
        recognized = True
        for source in sources.values():
            if not isinstance(source, dict):
                continue
            kind = source.get("type")
            if kind in _APP_MAP_SOURCE_TYPES:
                add(source.get("itemId"), kind, "app_web_map")
            else:
                add(
                    source.get("itemId"), kind, "app_data_source", source.get("layerId")
                )
    widgets = data.get("widgets")
    desktop = data.get("desktopView")
    if not isinstance(widgets, list) and isinstance(desktop, dict):
        widgets = desktop.get("widgets")
    if isinstance(widgets, list):
        recognized = True
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            add(widget.get("itemId"), widget.get("type"), "app_web_map")
            datasets = widget.get("datasets")
            for dataset in datasets if isinstance(datasets, list) else []:
                source = (
                    dataset.get("dataSource") if isinstance(dataset, dict) else None
                )
                if isinstance(source, dict):
                    add(
                        source.get("itemId"),
                        source.get("type"),
                        "app_data_source",
                        source.get("layerId"),
                    )
    if not recognized:
        return None
    unique: dict[tuple[str, str, str | None], tuple[str, str, str, str | None]] = {}
    for ref in found:
        unique.setdefault((ref[0], ref[2], ref[3]), ref)
    return list(unique.values())


def _extract_dependencies(
    row: Mapping[str, Any],
    data: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    portal: Mapping[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """(dependencies_status, dependency rows) for one item's data."""
    if row["type"] == _WEB_MAP_TYPE:
        return "parsed", web_map_dependencies(row["id"], data, index, portal)
    refs = _app_references(data)
    if refs is None:
        return "unparsed", []
    return "parsed", [
        _dependency(
            row["id"],
            ref,
            None,
            role=role,
            layer_type=kind,
            layer_id=layer_id,
            title=None,
            order=order,
            index=index,
            portal=portal,
        )
        for order, (ref, kind, role, layer_id) in enumerate(refs)
    ]


def _collect_dependencies(
    client: PortalClient, inv: Inventory, concurrency: int
) -> None:
    """Read each web map's and app's data and keep only its dependency rows.

    Each worker reduces the item's configuration to rows before returning,
    so at most *concurrency* full configurations are held at once.
    """
    index = {row["id"]: row for row in inv.items}
    targets = [row for row in inv.items if row["dependencies_status"] == "pending"]
    stop = threading.Event()

    def fetch(
        row: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]], PortalError | None]:
        if stop.is_set():
            return "not_fetched", [], None
        try:
            path = f"content/items/{quote(row['id'], safe='')}/data"
            data = client.get_json(path)
        except PortalError as exc:
            if exc.kind == "auth":
                stop.set()
                return "not_fetched", [], exc
            return "error", [], exc
        return (*_extract_dependencies(row, data, index, inv.portal), None)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(fetch, targets))

    for row, (status, dependencies, exc) in zip(targets, results, strict=True):
        row["dependencies_status"] = status
        inv.dependencies.extend(dependencies)
        if exc is not None and exc.kind == "auth":
            inv.abort = inv.abort or exc
        elif exc is not None:
            inv.errors.append(
                {
                    "item_id": row["id"],
                    "phase": "item_data",
                    "http_status": exc.http_status,
                    "message": str(exc),
                }
            )


def run_inventory(
    client: PortalClient,
    *,
    auth_mode: str,
    scope: str,
    max_items: int,
    concurrency: int,
) -> Inventory:
    """List, classify and resolve dependencies.

    A failure reading ``portals/self`` raises ``PortalError``. Any later
    listing failure, or a rejected token while reading item data, stops the
    run and is recorded as ``Inventory.abort``; everything gathered so far is
    kept for a partial report.
    """
    info = client.get_json("portals/self")
    user = info.get("user") if isinstance(info.get("user"), dict) else {}
    username = user.get("username") if isinstance(user.get("username"), str) else None
    org_id = info.get("id") if isinstance(info.get("id"), str) else None
    portal = {
        "url": client.root,
        "kind": "enterprise" if info.get("isPortal") else "online",
        "version": str(info["currentVersion"]) if info.get("currentVersion") else None,
        "org_id": org_id,
        "name": str(info["name"]) if info.get("name") else None,
    }
    if scope == "user" and not username:
        raise PortalError(
            "the portal did not report a signed-in user, so --scope user has "
            "nothing to list. Check the token, or use --scope org.",
            kind="auth",
        )
    if scope == "org" and not org_id:
        raise PortalError(
            "the portal did not report an organization id. Use the "
            "organization's own URL (https://<org>.maps.arcgis.com, or "
            "https://<host>/portal for ArcGIS Enterprise).",
            kind="usage",
        )
    inv = Inventory(
        portal=portal,
        auth={"mode": auth_mode, "user": username},
        scope={
            "mode": scope,
            "owner": username if scope == "user" else None,
            "org_id": org_id if scope == "org" else None,
        },
    )
    try:
        for raw in _list_items(client, inv, max_items):
            inv.items.append(_item_row(raw))
    except PortalError as exc:
        inv.abort = exc
        for row in inv.items:
            if row["dependencies_status"] == "pending":
                row["dependencies_status"] = "not_fetched"
        return inv
    _collect_dependencies(client, inv, concurrency)
    return inv


class InventoryScope(str, Enum):
    user = "user"
    org = "org"


@dataclass
class InventoryOptions:
    portal_url: str
    token: str | None
    token_stdin: bool
    username: str | None
    password_stdin: bool
    scope: str
    max_items: int
    concurrency: int
    output_dir: Path | None
    strict: bool
    allow_insecure_http: bool
    json_mode: bool


class _UsageError(Exception):
    pass


_EXIT_BY_KIND = {
    "auth": EXIT_AUTH,
    "network": EXIT_NETWORK,
    "server": EXIT_SERVER,
    "redirect": EXIT_USAGE,
    "usage": EXIT_USAGE,
}


def _portal_root(url: str, allow_insecure_http: bool) -> str:
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        host = None
        parts = None
    if parts is None or not host:
        raise _UsageError("--portal-url must be an absolute URL")
    if parts.scheme != "https" and not (parts.scheme == "http" and allow_insecure_http):
        raise _UsageError(
            "--portal-url must use https (http only with --allow-insecure-http)"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise _UsageError(
            "--portal-url must not carry credentials, a query string or a fragment"
        )
    path = parts.path.rstrip("/")
    for suffix in ("/sharing/rest", "/home"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
    return f"{parts.scheme}://{parts.netloc}{path}"


def _resolve_credentials(opts: InventoryOptions) -> tuple[str, str | None, str | None]:
    """(auth mode, token, password)."""
    token = opts.token or None
    if opts.token_stdin and token:
        raise _UsageError("pass the token once: --token/ARCGIS_TOKEN or --token-stdin")
    if opts.username and (token or opts.token_stdin):
        raise _UsageError("use either a token or --username, not both")
    if opts.password_stdin and not opts.username:
        raise _UsageError("--password-stdin needs --username")
    if opts.token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            raise _UsageError("--token-stdin read an empty line")
    if token is not None:
        if not _TOKEN_CHARS.fullmatch(token):
            raise _UsageError(
                "the ArcGIS token holds whitespace or non-ASCII characters, "
                "which no ArcGIS token has"
            )
        return "token", token, None
    if opts.username:
        if opts.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = os.environ.get("ARCGIS_PASSWORD") or getpass.getpass(
                "ArcGIS password: "
            )
        if not password:
            raise _UsageError("an empty password was given")
        return "generateToken", None, password
    if opts.scope == "user":
        raise _UsageError(
            "--scope user needs a signed-in user: pass --token, ARCGIS_TOKEN, "
            "--token-stdin or --username, or use --scope org to list public items"
        )
    return "anonymous", None, None


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("geolens-cli")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _emit(fmt: _output.Formatter, opts: InventoryOptions, report: dict) -> None:
    markdown = _report.render_markdown(report)
    if opts.output_dir is not None:
        json_path, md_path = _report.write_report_files(
            opts.output_dir, report, markdown
        )
        fmt.success(f"Wrote {json_path} and {md_path}")
    elif opts.json_mode:
        fmt.json(report)
    else:
        sys.stdout.write(markdown)
        sys.stdout.flush()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _clock() -> float:
    return time.monotonic()


def run_cli(fmt: _output.Formatter, opts: InventoryOptions) -> int:
    """Run ``geolens arcgis inventory`` and return its exit code."""
    redact = Redactor()
    try:
        return _run(fmt, opts, redact)
    except (
        Exception
    ) as exc:  # broad: last guard so a traceback can't print a credential
        fmt.error(redact(f"unexpected error: {type(exc).__name__}: {exc}"))
        return EXIT_GENERIC


def _run(fmt: _output.Formatter, opts: InventoryOptions, redact: Redactor) -> int:
    try:
        if not 1 <= opts.concurrency <= MAX_CONCURRENCY:
            raise _UsageError(f"--concurrency must be between 1 and {MAX_CONCURRENCY}")
        if opts.max_items < 1:
            raise _UsageError("--max-items must be at least 1")
        root = _portal_root(opts.portal_url, opts.allow_insecure_http)
        auth_mode, token, password = _resolve_credentials(opts)
    except _UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    redact.add(token)
    redact.add(password)

    client = PortalClient(
        root,
        opener=build_opener(),
        redact=redact,
        token=token,
        sleep=_sleep,
        clock=_clock,
        on_request=lambda method, path: fmt.debug(redact(f"{method} {path}")),
    )
    try:
        if password is not None and opts.username:
            client.generate_token(opts.username, password)
        inv = run_inventory(
            client,
            auth_mode=auth_mode,
            scope=opts.scope,
            max_items=opts.max_items,
            concurrency=opts.concurrency,
        )
    except PortalError as exc:
        fmt.error(str(exc))
        return _EXIT_BY_KIND.get(exc.kind, EXIT_GENERIC)

    report = _report.build_report(
        inv,
        tool_version=_tool_version(),
        generated_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        max_items=opts.max_items,
        retirements=RETIREMENTS,
        classes=CLASSES,
    )
    _emit(fmt, opts, report)
    if inv.abort is not None:
        hint = (
            " The token was rejected mid-run (it may have expired); rerun with a fresh token."
            if inv.abort.kind == "auth"
            else ""
        )
        fmt.error(f"inventory stopped early, report is partial: {inv.abort}.{hint}")
        return _EXIT_BY_KIND.get(inv.abort.kind, EXIT_GENERIC)
    if inv.errors and opts.strict:
        fmt.error(f"{len(inv.errors)} item(s) could not be read (--strict)")
        return EXIT_GENERIC
    return EXIT_OK

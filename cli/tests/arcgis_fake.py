"""Offline ArcGIS portal double for the `geolens arcgis inventory` tests."""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

FIXTURES = Path(__file__).parent / "fixtures" / "arcgis_inventory"
PORTAL = "https://examplecounty.maps.arcgis.com"
ORG_ID = "ExAmPlEoRg0123"
USER = "gis_admin"
FOLDER = "f0" * 16
A1, A2, A3, A4, A5 = ("a1" * 16, "a2" * 16, "a3" * 16, "a4" * 16, "a5" * 16)
B1, B2 = "b1" * 16, "b2" * 16
C1, C2, C3 = "c1" * 16, "c2" * 16, "c3" * 16
D1, D2, D3, D4, D5 = ("d1" * 16, "d2" * 16, "d3" * 16, "d4" * 16, "d5" * 16)
HYDRANTS = "e9" * 16
EMPTY_GROUPS = {"admin": [], "member": [], "other": []}
NO_RELATED = {"total": 0, "relatedItems": []}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class Seen:
    method: str
    url: str
    headers: dict[str, str]
    body: str

    @property
    def path(self) -> str:
        return urlsplit(self.url).path.split("/sharing/rest/", 1)[-1]

    @property
    def params(self) -> dict[str, str]:
        params = dict(parse_qsl(urlsplit(self.url).query))
        params.update(parse_qsl(self.body))
        return params


def _message(headers: dict[str, str] | None) -> http.client.HTTPMessage:
    message = http.client.HTTPMessage()
    for name, value in (headers or {}).items():
        message[name] = value
    return message


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._buffer = io.BytesIO(body)
        self.headers = _message(headers)
        self.status = 200

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def read1(self, size: int = -1) -> bytes:
        return self._buffer.read1(size)

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakePortal:
    """Injected opener: answers by ``/sharing/rest/`` path, records requests.

    A route is a JSON dict (HTTP 200), a ``(status, body[, headers])`` tuple,
    an exception to raise, a callable taking the ``Seen`` request, or a list
    of any of these served in turn (the last one repeats).
    """

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.seen: list[Seen] = []

    def requests_to(self, path: str) -> list[Seen]:
        return [s for s in self.seen if s.path == path]

    def open(self, request: Any, timeout: float | None = None) -> _Response:
        body = request.data.decode() if request.data else ""
        headers = {k.lower(): v for k, v in request.header_items()}
        seen = Seen(request.get_method(), request.full_url, headers, body)
        self.seen.append(seen)
        reply = self.routes.get(seen.path, (404, {"error": {"code": 404}}))
        if isinstance(reply, list):
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        if callable(reply) and not isinstance(reply, type):
            reply = reply(seen)
        if isinstance(reply, BaseException):
            raise reply
        status, payload, extra = 200, reply, None
        if isinstance(reply, tuple):
            status, payload, *rest = reply
            extra = rest[0] if rest else None
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        if status >= 300:
            raise urllib.error.HTTPError(
                request.full_url, status, "fake", _message(extra), io.BytesIO(raw)
            )
        return _Response(raw, extra)


def portal_routes(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Routes for the fixture organization, with *overrides* replacing some."""

    def search(seen: Seen) -> dict:
        return load(
            "search_page1.json" if seen.params["start"] == "1" else "search_page2.json"
        )

    routes: dict[str, Any] = {
        "portals/self": load("portal_self.json"),
        "search": search,
        f"content/users/{USER}": load("user_content.json"),
        f"content/users/{USER}/{FOLDER}": load("user_folder.json"),
        f"content/items/{B1}/data": load("item_web_map_data.json"),
        f"content/items/{B2}/data": (500, load("item_data_500.json")),
        f"content/items/{C1}/data": load("item_wab_app_data.json"),
        f"content/items/{C2}/data": {"values": {"title": "Our county"}},
        f"content/items/{C3}/data": load("item_dashboard_data.json"),
        f"content/items/{D5}/data": load("item_web_scene_data.json"),
        "generateToken": load("generate_token_ok.json"),
    }
    for name in ("search_page1.json", "search_page2.json"):
        for listed in load(name)["results"]:
            routes[f"content/items/{listed['id']}"] = listed
            routes[f"content/items/{listed['id']}/groups"] = EMPTY_GROUPS
            routes[f"content/items/{listed['id']}/relatedItems"] = NO_RELATED
    routes[f"community/users/{USER}"] = {
        "username": USER,
        "fullName": "Gina Admin",
        "email": "gina.admin@example.org",
    }
    routes.update(overrides or {})
    return routes


def item_data_path(item_id: str) -> str:
    return f"content/items/{item_id}/data"

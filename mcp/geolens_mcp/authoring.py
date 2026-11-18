# SPDX-License-Identifier: Apache-2.0
"""Map authoring calls for a ``map_author`` API key.

Each write sends only fields that key scope may set: a map's name,
description, view and basemap, and a layer's dataset, paint, style_config and
popup_config. Styles are translated by ``styles`` into the builder's shape.
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from typing import Any, Optional
from urllib.parse import quote

from . import styles
from .client import APIError, GeoLensReadOnlyAPI, _id_segment

AUTHOR_KEY_NEEDED = (
    "Map authoring needs the MCP server to run with a map_author API key in "
    "GEOLENS_API_KEY, and that key can change only the maps it created."
)
BLANK_BASEMAP = "blank"
# Set by the tool wrapper when the MCP request is cancelled; the worker thread
# carries on, so every write checks it first.
CANCELLED: ContextVar[Optional[threading.Event]] = ContextVar(
    "geolens_mcp_cancelled", default=None
)
# The backend's fingerprint is the key's first 12 characters ("glk_" and 8
# more), an ellipsis and its last 4; the key list shows it, never the key.
_FINGERPRINT_HEAD = 12
_FINGERPRINT_TAIL = 4
_KEY_PAGE = 200
_RASTER_RECORD_TYPES = frozenset({"raster_dataset", "vrt_dataset"})


def _columns(column_info: Any) -> dict[str, str]:
    if not isinstance(column_info, list):
        return {}
    return {
        c["name"]: str(c.get("type") or "")
        for c in column_info
        if isinstance(c, dict) and isinstance(c.get("name"), str)
    }


class GeoLensAPI(GeoLensReadOnlyAPI):
    """The read calls plus map authoring.

    Authoring runs only when the configured credential is a ``map_author`` API
    key. A token or a key with another scope could write maps too, so a setup
    made for reading never gains write tools by upgrading the server.
    """

    _author_key: Optional[bool] = None

    def _write(self, method: str, path: str, body: dict[str, Any]) -> Any:
        event = CANCELLED.get()
        if event is not None and event.is_set():
            raise RuntimeError("The request was cancelled; nothing more was written.")
        return self._request(method, path, json=body, denied=AUTHOR_KEY_NEEDED)

    def _require_author_key(self) -> None:
        """Refuse unless the configured credential is a map_author API key."""
        with self._cache_lock:
            known = self._author_key
        if known is None:
            known = self._is_author_key()
            with self._cache_lock:
                self._author_key = known
        if not known:
            raise RuntimeError(AUTHOR_KEY_NEEDED)

    def _is_author_key(self) -> bool:
        key = self._http.headers.get("X-Api-Key")
        if not key:
            return False
        fingerprint = f"{key[:_FINGERPRINT_HEAD]}…{key[-_FINGERPRINT_TAIL:]}"
        skip = 0
        while True:
            try:
                page = self._get("/auth/api-keys/", {"skip": skip, "limit": _KEY_PAGE})
            except APIError as exc:
                # A publish key may not list keys, and a dataset key reads as
                # no key; neither is a map_author key.
                if exc.status in (401, 403):
                    return False
                raise
            items = page.get("items") if isinstance(page, dict) else None
            if not isinstance(items, list):
                return False
            for item in items:
                if isinstance(item, dict) and item.get("fingerprint") == fingerprint:
                    return bool(item.get("is_active")) and item.get("scope") == (
                        "map_author"
                    )
            skip += len(items)
            if not items or skip >= int(page.get("total") or 0):
                return False

    def _app_url(self, map_id: str) -> str:
        base = str(self._http.base_url).rstrip("/")
        if base.endswith("/api"):
            base = base[: -len("/api")]
        return f"{base}/maps/{map_id}"

    def _basemap_id(self, basemap: str) -> str:
        if basemap == BLANK_BASEMAP:
            return basemap
        listed = self._get("/settings/basemaps/")
        ids = [
            b["id"]
            for b in (listed if isinstance(listed, list) else [])
            if isinstance(b, dict) and b.get("enabled") and isinstance(b.get("id"), str)
        ]
        if basemap not in ids:
            raise ValueError(
                f"Unknown basemap {basemap!r}. Use one of: "
                + ", ".join([*ids, BLANK_BASEMAP])
            )
        return basemap

    def _map_view(self, detail: Any) -> dict[str, Any]:
        keys = (
            "id",
            "name",
            "visibility",
            "center_lng",
            "center_lat",
            "zoom",
            "pitch",
            "bearing",
            "basemap_style",
        )
        out = {k: detail.get(k) for k in keys} if isinstance(detail, dict) else {}
        out["url"] = self._app_url(out.get("id") or "")
        return out

    def create_map(
        self,
        name: str,
        description: Optional[str] = None,
        basemap: Optional[str] = None,
    ) -> Any:
        self._require_author_key()
        basemap_id = self._basemap_id(basemap) if basemap is not None else None
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        created = self._write("POST", "/maps/", body)
        if basemap_id is None:
            return self._map_view(created)
        map_id = _id_segment(created.get("id"))
        try:
            updated = self._write(
                "PUT", f"/maps/{map_id}", {"basemap_style": basemap_id}
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Map {map_id} was created, but its basemap was not set: {exc}"
            ) from exc
        return self._map_view(updated)

    def update_map_view(self, map_id: str, view: dict[str, Any]) -> Any:
        """Set any of center_lng, center_lat, zoom, pitch, bearing, basemap_style."""
        self._require_author_key()
        segment = _id_segment(map_id)
        if "basemap_style" in view:
            view = {**view, "basemap_style": self._basemap_id(view["basemap_style"])}
        return self._map_view(self._write("PUT", f"/maps/{segment}", view))

    def _style_inputs(
        self,
        dataset_id: str,
        columns: dict[str, str],
        style: Optional[dict[str, Any]],
    ) -> tuple[Optional[styles.StyleRequest], Any]:
        """Validate ``style`` and fetch the column values or stats it needs."""
        if style is None:
            return None, None
        request = styles.parse_style(style, columns)
        if request.column is None:
            return request, None
        column = quote(request.column, safe="")
        base = f"/datasets/{_id_segment(dataset_id)}/columns/{column}"
        if request.type == "categories":
            data = self._get(f"{base}/values/", {"limit": styles.MAX_CATEGORIES + 1})
            values = data.get("values") if isinstance(data, dict) else None
            return request, values if isinstance(values, list) else []
        if request.method == "manual":
            return request, {}
        stats = self._get(f"{base}/stats/")
        return request, stats if isinstance(stats, dict) else {}

    @staticmethod
    def _restyle(
        request: styles.StyleRequest,
        data: Any,
        geometry_type: Optional[str],
        layer: dict[str, Any],
    ) -> tuple[dict[str, Any], Optional[dict[str, Any]], dict[str, Any]]:
        paint = layer.get("paint") if isinstance(layer.get("paint"), dict) else {}
        config = layer.get("style_config")
        config = config if isinstance(config, dict) else None
        if request.type == "single":
            return styles.single_color(request, geometry_type, paint, config)
        if request.type == "categories":
            return styles.categories(request, data, geometry_type, paint, config)
        return styles.classes(request, data, geometry_type, paint, config)

    def add_layer(
        self,
        map_id: str,
        dataset_id: str,
        style: Optional[dict[str, Any]] = None,
        popup_fields: Optional[list[str]] = None,
    ) -> Any:
        map_segment = _id_segment(map_id)
        dataset_segment = _id_segment(dataset_id)
        self._require_author_key()
        dataset = self._get(f"/datasets/{dataset_segment}")
        if (style is not None or popup_fields is not None) and dataset.get(
            "record_type"
        ) in _RASTER_RECORD_TYPES:
            raise ValueError("A raster layer takes no style or popup fields")
        columns = _columns(dataset.get("column_info"))
        request, data = self._style_inputs(dataset_segment, columns, style)
        if request is not None:
            # A style the data can't take is refused before the layer exists.
            self._restyle(request, data, dataset.get("geometry_type"), {})
        body: dict[str, Any] = {"dataset_id": dataset_segment}
        if popup_fields is not None:
            body["popup_config"] = styles.popup_config(popup_fields, columns, None)
        layer = self._write("POST", f"/maps/{map_segment}/layers", body)
        result = {
            "map_id": map_segment,
            "layer_id": layer.get("id"),
            "dataset_id": dataset_segment,
            "style": None,
            "url": self._app_url(map_segment),
        }
        if request is None:
            return result
        paint, config, summary = self._restyle(
            request, data, layer.get("dataset_geometry_type"), layer
        )
        patch = {"id": layer.get("id"), "paint": paint, "style_config": config}
        try:
            self._write("PATCH", f"/maps/{map_segment}/layers", {"updated": [patch]})
        except RuntimeError as exc:
            raise RuntimeError(
                f"Layer {layer.get('id')} was added, but its style was not set: {exc}"
            ) from exc
        return {**result, "style": summary}

    def update_layer_style(
        self,
        map_id: str,
        layer_id: str,
        style: Optional[dict[str, Any]] = None,
        popup_fields: Optional[list[str]] = None,
    ) -> Any:
        if style is None and popup_fields is None:
            raise ValueError("Give a style, popup_fields or both")
        map_segment = _id_segment(map_id)
        layer_segment = _id_segment(layer_id)
        self._require_author_key()
        detail = self._get(f"/maps/{map_segment}")
        layer = next(
            (
                item
                for item in detail.get("layers") or []
                if isinstance(item, dict) and item.get("id") == layer_segment
            ),
            None,
        )
        if layer is None:
            raise ValueError(f"Map {map_segment} has no layer {layer_segment}")
        if layer.get("layer_type") == "raster_geolens":
            raise ValueError("A raster layer takes no style or popup fields")
        columns = _columns(layer.get("dataset_column_info"))
        request, data = self._style_inputs(layer.get("dataset_id"), columns, style)
        patch: dict[str, Any] = {"id": layer_segment}
        summary = None
        if request is not None:
            paint, config, summary = self._restyle(
                request, data, layer.get("dataset_geometry_type"), layer
            )
            patch.update(paint=paint, style_config=config)
        if popup_fields is not None:
            patch["popup_config"] = styles.popup_config(
                popup_fields, columns, layer.get("popup_config")
            )
        self._write("PATCH", f"/maps/{map_segment}/layers", {"updated": [patch]})
        return {
            "map_id": map_segment,
            "layer_id": layer_segment,
            "style": summary,
            "url": self._app_url(map_segment),
        }

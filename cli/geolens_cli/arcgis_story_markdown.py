# SPDX-License-Identifier: Apache-2.0
"""Render an ArcGIS story into Markdown for the export bundle.

Hand-maintained. Reads the ``/data`` of an ArcGIS StoryMaps item (a ``nodes``
tree) or a classic Story Map (``values.story``) and writes the readable
``story.md``: title, headings, paragraphs with bold and links, images as
relative links into ``resources/``, each map as a link, embeds as their URL.
A node type with no rendering becomes an HTML comment naming it.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from typing import Any

# Resolves an ArcGIS web map item id to the URL a reader should open: the
# GeoLens map made from it, or else the ArcGIS item.
MapLink = Callable[[str], str]

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
# Nodes that only group their children.
_CONTAINERS = frozenset(
    {
        "story",
        "immersive",
        "immersive-slide",
        "immersive-narrative-panel",
        "credits",
        "carousel",
    }
)
# A tour-map is read through the tour that owns it.
_SILENT = frozenset({"navigation", "story-theme", "tour-map"})
_MAX_DEPTH = 32
_BREAK = "\x00"


class _Inline(HTMLParser):
    """Inline HTML of a text node as Markdown."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._links.append(href)
            if href:
                self.parts.append("[")
        elif tag == "br":
            self.parts.append(_BREAK)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a" and self._links:
            href = self._links.pop()
            if href:
                self.parts.append(f"]({_link_target(href)})")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _link_target(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def inline_markdown(value: Any) -> str:
    """The inline HTML in *value* as Markdown text; tags it doesn't know are
    dropped and their text kept."""
    if not isinstance(value, str):
        return ""
    parser = _Inline()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts).replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text.replace(_BREAK, "\\\n")


def _text_block(data: Mapping[str, Any]) -> str:
    kind = data.get("type")
    text = inline_markdown(data.get("text"))
    if not text:
        return ""
    if kind in _HEADINGS:
        return f"{'#' * _HEADINGS[kind]} {text}"
    if kind == "quote":
        return "\n".join(f"> {line}" for line in text.splitlines())
    if kind in ("bullet-list", "numbered-list"):
        lines = [inline_markdown(i) for i in re.split(r"(?i)</?li>", str(data["text"]))]
        lines = [line for line in lines if line]
        numbered = kind == "numbered-list"
        return "\n".join(
            f"{n}. {line}" if numbered else f"- {line}"
            for n, line in enumerate(lines, 1)
        )
    return text


class _Story:
    def __init__(
        self, data: Mapping[str, Any], map_link: MapLink, resource_dir: str
    ) -> None:
        self.nodes: Mapping[str, Any] = data.get("nodes") or {}
        self.resources: Mapping[str, Any] = data.get("resources") or {}
        self.map_link = map_link
        self.resource_dir = resource_dir
        self.blocks: list[str] = []
        self.seen: set[str] = set()

    def walk(self, node_id: str, depth: int = 0) -> None:
        node = self.nodes.get(node_id)
        if not isinstance(node, Mapping) or depth > _MAX_DEPTH or node_id in self.seen:
            return
        self.seen.add(node_id)
        kind = str(node.get("type"))
        data = node.get("data") if isinstance(node.get("data"), Mapping) else {}
        if kind == "storycover":
            self._cover(data)
        elif kind in _CONTAINERS:
            pass
        elif kind in _SILENT:
            return
        elif kind == "text":
            self._add(_text_block(data))
        elif kind == "image":
            self._image(data)
        elif kind == "webmap":
            self._map(data)
        elif kind in ("embed", "video"):
            url = data.get("url") or data.get("embedSrc")
            title = inline_markdown(data.get("title")) or str(url)
            self._add(f"[{title}]({_link_target(str(url))})" if url else "")
        elif kind == "separator":
            self._add("---")
        elif kind == "attribution":
            self._add(inline_markdown(data.get("attribution") or data.get("content")))
        elif kind == "tour":
            self._tour(data, depth)
        else:
            # Read the nodes an unknown node refers to, so its text and images
            # are never dropped; only a node with nothing in it is a comment.
            found = self._referenced(data)
            for ref in found:
                self.walk(ref, depth + 1)
            if not found and not node.get("children"):
                self._add(f"<!-- unsupported node type: {html.escape(kind)} -->")
        for child in node.get("children") or []:
            self.walk(str(child), depth + 1)

    def _referenced(self, value: Any, depth: int = 0) -> list[str]:
        """Node ids named in *value*, in order."""
        if depth > _MAX_DEPTH:
            return []
        if isinstance(value, str):
            return [value] if value in self.nodes else []
        if isinstance(value, Mapping):
            value = list(value.values())
        if isinstance(value, list):
            return [r for v in value for r in self._referenced(v, depth + 1)]
        return []

    def _tour(self, data: Mapping[str, Any], depth: int) -> None:
        """A guided tour: each place's title, where it is, its media, then its
        text. The tour node has no children; the places hold the content."""
        tour_map = self.nodes.get(str(data.get("map")))
        shapes = {}
        if isinstance(tour_map, Mapping) and isinstance(tour_map.get("data"), Mapping):
            shapes = tour_map["data"].get("geometries") or {}
        for place in data.get("places") or []:
            if not isinstance(place, Mapping):
                continue
            self.walk(str(place.get("title")), depth + 1)
            self._location(shapes.get(str(place.get("featureId"))))
            self.walk(str(place.get("media")), depth + 1)
            for content in place.get("contents") or []:
                self.walk(str(content), depth + 1)

    def _location(self, shape: Any) -> None:
        nodes = shape.get("nodes") if isinstance(shape, Mapping) else None
        point = nodes[0] if isinstance(nodes, list) and nodes else None
        if isinstance(point, Mapping):
            lat, long = point.get("lat"), point.get("long")
            if isinstance(lat, int | float) and isinstance(long, int | float):
                self._add(f"*Location: {lat:.5f}, {long:.5f}*")

    def _add(self, block: str) -> None:
        if block:
            self.blocks.append(block)

    def _cover(self, data: Mapping[str, Any]) -> None:
        self._add(f"# {inline_markdown(data.get('title'))}")
        self._add(inline_markdown(data.get("byline")))
        self._add(inline_markdown(data.get("summary")))

    def _image(self, data: Mapping[str, Any]) -> None:
        resource = self.resources.get(str(data.get("image")))
        info = resource.get("data") if isinstance(resource, Mapping) else None
        name = info.get("resourceId") if isinstance(info, Mapping) else None
        if not isinstance(name, str):
            self._add("<!-- image without a stored file -->")
            return
        caption = inline_markdown(data.get("caption") or data.get("attribution"))
        self._add(f"![{caption}]({self.resource_dir}{quote(name, safe='/')})")

    def _map(self, data: Mapping[str, Any]) -> None:
        resource = self.resources.get(str(data.get("map")))
        info = resource.get("data") if isinstance(resource, Mapping) else None
        item_id = info.get("itemId") if isinstance(info, Mapping) else None
        if not isinstance(item_id, str):
            self._add("<!-- map without an item -->")
            return
        caption = inline_markdown(data.get("caption")) or "Map"
        self._add(f"[Map: {caption}]({_link_target(self.map_link(item_id))})")


def render_storymap(
    data: Mapping[str, Any],
    *,
    title: str,
    map_link: MapLink,
    resource_dir: str = "resources/",
) -> str:
    """``story.md`` for an ArcGIS StoryMaps ``/data`` document.

    The item *title* heads the page when the story has no cover node.
    """
    story = _Story(data, map_link, resource_dir)
    story.walk(str(data.get("root")))
    if not any(block.startswith("# ") for block in story.blocks):
        story.blocks.insert(0, f"# {title}")
    return "\n\n".join(story.blocks) + "\n"


_BLOCK_END = re.compile(r"(?i)</(?:p|div|h[1-6]|li|ul|ol|blockquote|section)\s*>")


def block_markdown(value: Any) -> str:
    """Block HTML as Markdown paragraphs: each closing block tag ends one."""
    if not isinstance(value, str):
        return ""
    parts = (inline_markdown(part) for part in _BLOCK_END.split(value))
    return "\n\n".join(part for part in parts if part)


def render_classic(
    data: Mapping[str, Any], *, title: str, map_link: MapLink
) -> str | None:
    """``story.md`` for a classic Story Map's ``/data`` (``values.story``);
    None when *data* holds no story."""
    values = data.get("values")
    story = values.get("story") if isinstance(values, Mapping) else None
    if not isinstance(story, Mapping):
        return None
    blocks = [f"# {inline_markdown(values.get('title')) or title}"]
    if values.get("subtitle"):
        blocks.append(inline_markdown(values.get("subtitle")))
    for entry in story.get("entries") or story.get("sections") or []:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("title"):
            blocks.append(f"## {inline_markdown(entry.get('title'))}")
        if entry.get("contents"):
            blocks.append(block_markdown(entry.get("contents")))
        media = entry.get("media") if isinstance(entry.get("media"), Mapping) else {}
        webmap = media.get("webmap")
        if isinstance(webmap, Mapping) and isinstance(webmap.get("id"), str):
            blocks.append(f"[Map]({_link_target(map_link(webmap['id']))})")
        image = media.get("image")
        if isinstance(image, Mapping) and isinstance(image.get("url"), str):
            blocks.append(f"![]({_link_target(image['url'])})")
    return "\n\n".join(b for b in blocks if b) + "\n"

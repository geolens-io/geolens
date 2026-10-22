"""Story rendering for the export bundle."""

from __future__ import annotations

import json
from pathlib import Path

from geolens_cli import arcgis_story_markdown as story

FIXTURES = Path(__file__).parent / "fixtures" / "arcgis_story"
WEB_MAP = "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"


def _link(item_id: str) -> str:
    return f"https://maps.example/{item_id}"


def test_a_storymap_renders_to_the_golden_markdown():
    data = json.loads((FIXTURES / "storymap_data.json").read_text())

    text = story.render_storymap(data, title="Fallback", map_link=_link)

    assert text == (FIXTURES / "storymap_expected.md").read_text()


def test_a_map_node_links_to_the_url_the_resolver_names():
    data = json.loads((FIXTURES / "storymap_data.json").read_text())

    text = story.render_storymap(data, title="t", map_link=lambda i: f"geolens/{i}")

    assert f"(geolens/{WEB_MAP})" in text


def test_a_story_without_a_cover_is_headed_by_the_item_title():
    data = {"root": "a", "nodes": {"a": {"type": "story", "children": []}}}

    assert story.render_storymap(data, title="My story", map_link=_link) == (
        "# My story\n"
    )


def test_a_cyclic_tree_does_not_loop():
    data = {"root": "a", "nodes": {"a": {"type": "story", "children": ["a"]}}}

    assert story.render_storymap(data, title="t", map_link=_link).startswith("# t")


def test_a_classic_story_map_renders_entries_and_maps():
    data = {
        "values": {
            "title": "Classic",
            "subtitle": "Sub",
            "story": {
                "entries": [
                    {
                        "title": "First",
                        "contents": "<p>Hello <b>there</b></p>",
                        "media": {"type": "webmap", "webmap": {"id": WEB_MAP}},
                    },
                    {
                        "title": "Second",
                        "media": {"image": {"url": "https://x.org/a.png"}},
                    },
                ]
            },
        }
    }

    text = story.render_classic(data, title="t", map_link=_link)

    assert text == (
        "# Classic\n\nSub\n\n## First\n\nHello **there**\n\n"
        f"[Map]({_link(WEB_MAP)})\n\n## Second\n\n![](https://x.org/a.png)\n"
    )


def test_a_classic_page_without_a_story_renders_nothing():
    assert (
        story.render_classic({"values": {"title": "x"}}, title="t", map_link=_link)
        is None
    )

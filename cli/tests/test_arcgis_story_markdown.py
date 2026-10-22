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


def _tour() -> dict:
    return json.loads((FIXTURES / "tour_data.json").read_text())


def test_a_guided_tour_renders_each_place_in_order():
    text = story.render_storymap(_tour(), title="t", map_link=_link)

    assert text == (
        "# Blue Ways\n\nPaddle trails.\n\n"
        "### Downtown Blue Way\n\n*Location: 34.74273, -77.43146*\n\n"
        "![](resources/one.png)\n\n![Marina](resources/two.png)\n\n"
        "Three city **parks**.\n\n"
        "### River Blue Way\n\n*Location: 34.70000, -77.40000*\n\n"
        "![](resources/three.jpg)\n\nA longer route.\n\n"
        "Inside an unknown node.\n"
    )


def test_every_text_and_image_of_a_story_reaches_the_markdown():
    data = _tour()

    text = story.render_storymap(data, title="t", map_link=_link)

    for node in data["nodes"].values():
        if node["type"] == "text":
            assert story.inline_markdown(node["data"]["text"]) in text
    for resource in data["resources"].values():
        assert f"resources/{resource['data']['resourceId']}" in text


def test_an_unknown_node_with_nothing_in_it_is_a_comment():
    data = {
        "root": "a",
        "nodes": {"a": {"type": "story", "children": ["b"]}, "b": {"type": "widget"}},
    }

    assert "<!-- unsupported node type: widget -->" in story.render_storymap(
        data, title="t", map_link=_link
    )


def test_local_image_links_encode_characters_a_link_would_misread():
    data = {
        "root": "a",
        "nodes": {
            "a": {"type": "story", "children": ["b"]},
            "b": {"type": "image", "data": {"image": "r"}},
        },
        "resources": {"r": {"type": "image", "data": {"resourceId": "a#b?c d(1).png"}}},
    }

    text = story.render_storymap(data, title="t", map_link=_link)

    assert "![](resources/a%23b%3Fc%20d%281%29.png)" in text


def test_classic_story_contents_keep_their_paragraph_boundaries():
    data = {
        "values": {
            "story": {
                "entries": [
                    {
                        "title": "T",
                        "contents": "<p>First</p><p>Second <b>bold</b></p><div>Third</div>",
                    }
                ]
            }
        }
    }

    text = story.render_classic(data, title="t", map_link=_link)

    assert "First\n\nSecond **bold**\n\nThird" in text


def test_a_tour_with_invalid_geometries_still_renders_its_text():
    data = _tour()
    data["nodes"]["n-tourmap"]["data"]["geometries"] = ["not", "a", "mapping"]

    text = story.render_storymap(data, title="t", map_link=_link)

    assert "### Downtown Blue Way" in text and "Location:" not in text


def test_an_image_missing_from_the_saved_set_becomes_a_comment():
    data = _tour()

    text = story.render_storymap(
        data, title="t", map_link=_link, available={"one.png", "three.jpg"}
    )

    assert "![](resources/one.png)" in text and "two.png" not in text
    assert "<!-- image not saved in the export -->" in text

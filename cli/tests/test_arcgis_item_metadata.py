"""Mapping ArcGIS item metadata to GeoLens dataset fields."""

from __future__ import annotations

from geolens_cli.arcgis_item_metadata import html_to_text, item_metadata


def test_html_becomes_plain_text():
    html = (
        "<div><h3>About</h3><p>Roads &amp; trails<br>by county</p>"
        "<script>alert(1)</script><ul><li>One</li><li>Two</li></ul></div>"
    )
    assert html_to_text(html) == "About\nRoads & trails\nby county\nOne\nTwo"


def test_plain_text_passes_through():
    assert html_to_text("  Just   words  ") == "Just words"
    assert html_to_text(None) == ""


def test_fields_are_capped_to_the_api_limits():
    row = {
        "snippet": "S",
        "description": "D" * 6000,
        "license_info": "L" * 1200,
        "access_information": "A",
    }
    fields = item_metadata(row, {"tags": []}, {"name": "N" * 1200})
    assert len(fields["summary"]) == 5000 and fields["summary"].startswith("S\n\nD")
    assert len(fields["license"]) == 1000
    assert len(fields["source_organization"]) == 1000


def test_empty_fields_are_left_out_and_tags_deduplicated():
    fields = item_metadata({}, {"tags": [" roads ", "roads", "", "trails"]}, None)
    assert fields == {"keywords": ["roads", "trails"]}


def test_entities_are_decoded_once():
    assert html_to_text("<p>a &amp;lt; b</p>") == "a &lt; b"


def test_an_attribution_never_carries_angle_brackets():
    row = {
        "access_information": "County GIS &lt;gis@example.org&gt; <b>&amp;</b> a < b"
    }
    fields = item_metadata(row, {"tags": []}, None)
    assert fields["attribution"] == "County GIS (gis@example.org) & a ( b"


def test_table_cells_keep_a_separator():
    html = "<table><tr><td>CC BY</td><td>4.0</td></tr><tr><th>A</th><th>B</th></tr></table>"
    assert html_to_text(html) == "CC BY 4.0\nA B"


def test_text_is_normalized_like_geolens_stores_it():
    decomposed = "Cafe\u0301 map"
    fields = item_metadata({"snippet": decomposed}, {"tags": []}, {"name": decomposed})
    assert fields["summary"] == "Caf\u00e9 map"
    assert fields["source_organization"] == "Caf\u00e9 map"


def test_a_tag_is_normalized_before_it_is_cut():
    tag = "a" * 499 + "e\u0301"
    fields = item_metadata({}, {"tags": [tag]}, None)
    assert fields["keywords"] == ["a" * 499 + "\u00e9"]


def test_angle_bracketed_literal_text_is_kept():
    assert (
        html_to_text("County GIS <gis@example.org>") == "County GIS <gis@example.org>"
    )
    assert html_to_text("<p>See <https://example.org/license> for terms</p>") == (
        "See <https://example.org/license> for terms"
    )
    fields = item_metadata(
        {"access_information": "County GIS <gis@example.org>"}, {"tags": []}, None
    )
    assert fields["attribution"] == "County GIS (gis@example.org)"


def test_every_block_element_is_a_text_boundary():
    assert html_to_text("<dl><dt>License</dt><dd>CC0</dd></dl>") == "License\nCC0"
    assert html_to_text("<blockquote>CC BY</blockquote>4.0") == "CC BY\n4.0"
    assert html_to_text("<h6>Use</h6><pre>free</pre>") == "Use\nfree"


def test_an_image_keeps_its_alt_text():
    html = '<p>License: <img alt="CC BY 4.0" src="badge.png"><img src="x.png"></p>'
    assert html_to_text(html) == "License: CC BY 4.0"


def test_center_is_a_boundary_and_self_closing_literals_appear_once():
    assert html_to_text("<center>License</center>CC0") == "License\nCC0"
    assert html_to_text("See <https://example.org/> for terms") == (
        "See <https://example.org/> for terms"
    )
    assert html_to_text("a<br/>b") == "a\nb"

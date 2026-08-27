"""Acceptance matrix for BasemapEntry.validate_tile_url (settings/schemas.py).

feat(pmtiles): the validator gained two new accepted shapes -- a bare
`https://....pmtiles` archive URL and a `pmtiles://`-prefixed one -- alongside
the pre-existing style JSON / /styles/ / {z}/{x}/{y} template shapes. This
pins both the new acceptances and that nothing else was loosened.
"""

import pytest
from pydantic import ValidationError

from app.modules.settings.schemas import BasemapEntry


def _entry(url: str) -> BasemapEntry:
    return BasemapEntry(id="test", label="Test", url=url)


class TestPreExistingShapesUnaffected:
    """Guard against the new branch loosening what was already accepted."""

    def test_style_json_url_accepted(self):
        assert _entry("https://tiles.openfreemap.org/styles/bright.json").url == (
            "https://tiles.openfreemap.org/styles/bright.json"
        )

    def test_styles_path_without_json_extension_accepted(self):
        assert _entry("https://tiles.openfreemap.org/styles/bright").url == (
            "https://tiles.openfreemap.org/styles/bright"
        )

    def test_xyz_template_accepted(self):
        url = "https://tile.example.com/{z}/{x}/{y}.png"
        assert _entry(url).url == url

    def test_xyz_template_with_api_key_placeholder_accepted(self):
        url = "https://tile.example.com/{z}/{x}/{y}.png?key={api_key}"
        assert _entry(url).url == url

    def test_garbage_url_still_rejected(self):
        with pytest.raises(ValidationError):
            _entry("https://example.com/not-a-recognized-shape")


class TestPmtilesArchiveAccepted:
    def test_bare_https_pmtiles_url_accepted(self):
        url = "https://example.com/basemaps/world.pmtiles"
        assert _entry(url).url == url

    def test_bare_http_pmtiles_url_accepted(self):
        url = "http://internal.example.com/world.pmtiles"
        assert _entry(url).url == url

    def test_pmtiles_scheme_prefixed_https_url_accepted(self):
        url = "pmtiles://https://example.com/basemaps/world.pmtiles"
        assert _entry(url).url == url

    def test_pmtiles_scheme_prefixed_http_url_accepted(self):
        url = "pmtiles://http://internal.example.com/world.pmtiles"
        assert _entry(url).url == url

    def test_bare_pmtiles_url_with_query_string_accepted(self):
        url = "https://example.com/world.pmtiles?token=abc123"
        assert _entry(url).url == url

    def test_pmtiles_scheme_prefixed_url_with_query_string_accepted(self):
        url = "pmtiles://https://example.com/world.pmtiles?token=abc123"
        assert _entry(url).url == url

    def test_pmtiles_extension_case_insensitive(self):
        url = "https://example.com/world.PMTiles"
        assert _entry(url).url == url


class TestPmtilesArchiveRejected:
    def test_pmtiles_scheme_with_no_inner_url_rejected(self):
        with pytest.raises(ValidationError):
            _entry("pmtiles://")

    def test_pmtiles_scheme_with_malformed_inner_url_rejected(self):
        with pytest.raises(ValidationError):
            _entry("pmtiles://not-a-url.pmtiles")

    def test_wrong_extension_rejected(self):
        with pytest.raises(ValidationError):
            _entry("https://example.com/world.mbtiles")

    def test_non_http_inner_scheme_rejected(self):
        with pytest.raises(ValidationError):
            _entry("pmtiles://ftp://example.com/world.pmtiles")

    def test_inner_url_missing_host_rejected(self):
        with pytest.raises(ValidationError):
            _entry("pmtiles://https:///world.pmtiles")

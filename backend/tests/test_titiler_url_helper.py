"""Tests for the Titiler COG URL helper (REMED-04 / P2-01).

Pins:
- Helper output shape for every Titiler call site (info, statistics, tiles).
- URL-encoding of caller-supplied query parameters (the `url=` key in
  particular, which carries user-supplied STAC asset hrefs).
- raw_query_suffix passthrough for the pre-built render-params string
  (which uses repeated `bidx` keys that urlencode would dedupe).
- Structural regression: every caller imports the helper and contains
  zero literal `http://titiler:8000` strings (Task 4).
"""

from app.platform.storage.titiler_url import build_titiler_cog_url


def test_build_titiler_cog_url_no_query():
    """Bare endpoint — no query — produces canonical Titiler info URL."""
    assert build_titiler_cog_url("info") == "http://titiler:8000/cog/info"


def test_build_titiler_cog_url_with_query():
    """User-supplied URL is URL-encoded into the query string."""
    result = build_titiler_cog_url(
        "info", query={"url": "https://example.com/foo.tif"}
    )
    assert result == "http://titiler:8000/cog/info?url=https%3A%2F%2Fexample.com%2Ffoo.tif"


def test_build_titiler_cog_url_with_raw_suffix():
    """raw_query_suffix is preserved verbatim (supports repeated keys like bidx)."""
    result = build_titiler_cog_url(
        "tiles/WebMercatorQuad/5/10/15.png",
        raw_query_suffix="bidx=1&bidx=2&rescale=0,255",
    )
    assert result == (
        "http://titiler:8000/cog/tiles/WebMercatorQuad/5/10/15.png"
        "?bidx=1&bidx=2&rescale=0,255"
    )


def test_build_titiler_cog_url_combines_query_and_raw_suffix():
    """Both query and raw_query_suffix supplied — combined with `&`."""
    result = build_titiler_cog_url(
        "tiles/WebMercatorQuad/5/10/15.png",
        query={"url": "https://example.com/foo.tif"},
        raw_query_suffix="bidx=1&bidx=2&rescale=0,255",
    )
    assert result == (
        "http://titiler:8000/cog/tiles/WebMercatorQuad/5/10/15.png"
        "?url=https%3A%2F%2Fexample.com%2Ffoo.tif"
        "&bidx=1&bidx=2&rescale=0,255"
    )


def test_build_titiler_cog_url_strips_leading_question_or_amp_from_raw_suffix():
    """raw_query_suffix tolerates a leading `?` or `&` (caller may pre-mark it).

    Output must never produce `??bidx=1` or `?&bidx=1`.
    """
    # leading ?
    result_q = build_titiler_cog_url("info", raw_query_suffix="?bidx=1")
    assert result_q == "http://titiler:8000/cog/info?bidx=1"

    # leading &
    result_amp = build_titiler_cog_url("info", raw_query_suffix="&bidx=1")
    assert result_amp == "http://titiler:8000/cog/info?bidx=1"


def test_build_titiler_cog_url_handles_tiles_path():
    """Endpoint with nested slashes (Titiler tiles route) is preserved verbatim."""
    result = build_titiler_cog_url("tiles/WebMercatorQuad/5/10/15.png")
    assert result == "http://titiler:8000/cog/tiles/WebMercatorQuad/5/10/15.png"

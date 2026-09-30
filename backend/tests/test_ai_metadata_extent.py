"""The AI metadata prompt describes a dataset's extent without hemisphere-like labels."""

from app.processing.ai.metadata_service import _describe_extent


def test_east_and_north_extent_reads_as_signed_ranges():
    text = _describe_extent((7.6, 45.95, 7.64, 46.01))

    assert "longitude 7.6000 to 7.6400" in text
    assert "latitude 45.9500 to 46.0100" in text
    assert "negative longitude is west" in text
    assert "(W, S, E, N)" not in text


def test_west_and_south_values_stay_negative():
    text = _describe_extent((-74.18, -40.9, -73.79, -40.55))

    assert "longitude -74.1800 to -73.7900" in text
    assert "latitude -40.9000 to -40.5500" in text


def test_seam_crossing_extent_is_spelled_out():
    text = _describe_extent((170.0, -20.0, -170.0, -10.0))

    assert "longitude 170.0000 to -170.0000 (crosses the antimeridian)" in text


def test_ordinary_extent_does_not_claim_a_crossing():
    assert "antimeridian" not in _describe_extent((7.6, 45.95, 7.64, 46.01))

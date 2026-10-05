"""A public response tells shared caches to drop it within SHARED_CACHE_MAX_AGE seconds."""

import pytest

from app.platform.cache.scope import (
    SHARED_CACHE_MAX_AGE,
    bound_shared_cache_lifetime,
    public_cache_control,
)
from app.processing.tiles.responses import _serving_tile_headers


@pytest.mark.parametrize(
    "value,expected",
    [
        ("public, max-age=300", "public, max-age=300, s-maxage=60"),
        ("public, max-age=30", "public, max-age=30, s-maxage=30"),
        ("public, max-age=0", "public, max-age=0, s-maxage=0"),
        ("public, max-age=60, s-maxage=86400", "public, max-age=60, s-maxage=60"),
        ("public, S-MAXAGE=86400, max-age=600", "public, max-age=600, s-maxage=60"),
        ("public, max-age=600, s-maxage=10", "public, max-age=600, s-maxage=10"),
        ('public, max-age="20"', 'public, max-age="20", s-maxage=20'),
        (
            "public, max-age=600, stale-while-revalidate=86400, stale-if-error=86400",
            "public, max-age=600, s-maxage=60",
        ),
        (
            "public, max-age=600, immutable",
            "public, max-age=600, immutable, s-maxage=60",
        ),
    ],
)
def test_the_shared_lifetime_never_exceeds_the_cap(value, expected):
    assert bound_shared_cache_lifetime(value) == expected


def test_public_cache_control_keeps_the_browser_lifetime():
    assert SHARED_CACHE_MAX_AGE == 60
    assert public_cache_control(3600) == "public, max-age=3600, s-maxage=60"


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize(
    "override", [None, "public, max-age=600, s-maxage=86400, stale-if-error=600"]
)
def test_a_public_tile_is_bounded_with_or_without_a_hosted_policy(empty, override):
    headers = _serving_tile_headers("public", 300, override, empty=empty)
    expected_max_age = 300 if override is None else 600
    assert headers["Cache-Control"] == (
        f"public, max-age={expected_max_age}, s-maxage=60"
    )
    assert "Vary" not in headers


@pytest.mark.parametrize("empty", [False, True])
def test_a_private_tile_takes_no_shared_lifetime(empty):
    headers = _serving_tile_headers(
        "private", 300, "public, max-age=600, s-maxage=86400", empty=empty
    )
    assert headers["Cache-Control"] == "private, max-age=300"

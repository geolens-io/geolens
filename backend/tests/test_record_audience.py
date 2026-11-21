"""What a version 2 manifest entry publishes, rule by rule."""

from __future__ import annotations

import pytest

from app.platform.record_audience import (
    Publication,
    PublicationRefused,
    effective_publication,
    may_set_public,
)

# (requested, status, fallback, may_set_public, is_key, now) -> Publication or
# the refusal's reason.
CASES = [
    # A create: omitted is private, a named level is kept.
    ("create-omitted", (None, "published", None, True, False, None), ("private", None)),
    (
        "create-internal",
        ("internal", "draft", None, True, False, None),
        ("internal", None),
    ),
    (
        "create-public",
        ("public", "published", None, True, False, None),
        ("public", None),
    ),
    # A refused public falls back only when asked.
    (
        "create-public-restricted",
        ("public", "published", None, False, False, None),
        "restriction",
    ),
    (
        "create-public-restricted-fallback",
        ("public", "published", "internal", False, False, None),
        ("internal", "restriction"),
    ),
    ("create-public-key", ("public", "published", None, True, True, None), "key"),
    (
        "create-public-key-fallback",
        ("public", "published", "internal", True, True, None),
        ("internal", "key"),
    ),
    (
        "create-key-omitted",
        (None, "published", None, False, True, None),
        ("private", None),
    ),
    # An update: omitted keeps the record's level.
    (
        "update-omitted",
        (None, "published", None, True, False, ("internal", "draft")),
        (None, None),
    ),
    (
        "update-omitted-public-draft",
        (None, "published", None, False, False, ("public", "draft")),
        (None, None),
    ),
    (
        "update-public-restricted",
        ("public", "published", None, False, False, ("internal", "draft")),
        "restriction",
    ),
    # A key never opens a record to anonymous readers...
    (
        "update-key-opens",
        (None, "published", None, False, True, ("public", "draft")),
        "key",
    ),
    (
        "update-key-opens-fallback",
        (None, "published", "internal", False, True, ("public", "draft")),
        ("internal", "key"),
    ),
    (
        "update-key-keeps-published",
        (None, "published", None, False, True, ("public", "published")),
        (None, None),
    ),
    (
        "update-key-publishes-internal",
        (None, "published", None, False, True, ("internal", "draft")),
        (None, None),
    ),
    # ...and never widens, a fallback included; it may narrow.
    (
        "update-key-widens",
        ("internal", "draft", None, False, True, ("private", "draft")),
        "widening",
    ),
    (
        "update-key-fallback-widens",
        ("public", "draft", "internal", False, True, ("private", "draft")),
        "widening",
    ),
    (
        "update-key-narrows",
        ("private", "published", None, False, True, ("public", "draft")),
        ("private", None),
    ),
    (
        "update-key-fallback-narrows",
        ("public", "published", "internal", False, True, ("public", "draft")),
        ("internal", "key"),
    ),
    # The may-set flag never lets a key name public.
    (
        "update-key-public-allowed-flag",
        ("public", "published", None, True, True, ("public", "published")),
        "key",
    ),
]


@pytest.mark.parametrize(
    "arguments,expected", [case[1:] for case in CASES], ids=[case[0] for case in CASES]
)
def test_effective_publication(arguments, expected):
    requested, status, fallback, may_set, is_key, now = arguments
    run = lambda: effective_publication(  # noqa: E731
        requested,
        status,
        fallback,
        may_set_public=may_set,
        is_key=is_key,
        now=now,
    )
    if isinstance(expected, str):
        with pytest.raises(PublicationRefused) as refused:
            run()
        assert refused.value.reason == expected
        return
    visibility, fell_back_for = expected
    assert run() == Publication(visibility, status, fell_back_for)


@pytest.mark.parametrize(
    "is_key,is_admin,restricted,allowed",
    [
        (False, False, False, True),
        (False, False, True, False),
        (False, True, True, True),
        (True, True, False, False),
    ],
    ids=["unrestricted", "restricted", "admin", "key"],
)
def test_may_set_public(is_key, is_admin, restricted, allowed):
    assert (
        may_set_public(is_key=is_key, is_admin=is_admin, restricted=restricted)
        is allowed
    )

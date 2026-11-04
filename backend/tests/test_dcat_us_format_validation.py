"""DCAT-US validation enforces the JSON Schema ``date-time`` and ``iri`` formats."""

from __future__ import annotations

import pytest

from app.standards.dcat_us.validation import validate_dcat_us3


def _paths(report: dict) -> set[str]:
    return {error["path"] for error in report["errors"]}


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("2024-01-15T10:30:00Z", True),
        ("2024-13-45T99:99:99Z", False),
    ],
)
def test_date_time_format_is_enforced(value, accepted):
    report = validate_dcat_us3({"created": value}, "DataService")
    assert ("$.created" not in _paths(report)) is accepted


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("https://example.org/id/1", True),
        ("not an iri", False),
    ],
)
def test_iri_format_is_enforced(value, accepted):
    report = validate_dcat_us3({"@id": value}, "Dataset")
    assert ("$.@id" not in _paths(report)) is accepted


def _distribution(url: str, description: str | None = None):
    from app.standards.distributions import PublishedDistribution

    return PublishedDistribution(
        distribution_type="vector_tiles",
        format="PNG",
        url=url,
        title="Tiles",
        description=description,
        media_type="image/png",
    )


def test_templated_distribution_url_is_replaced_by_a_real_iri():
    """A URI template never reaches accessURL or endpointURL; it moves to the description."""
    from app.standards.dcat_us.service import _distribution_to_dcat_us3

    template = "https://x.test/tiles/{z}/{x}/{y}.png?v=1"
    landing = "https://x.test/datasets/abc/dcat-us/3.0"
    out = _distribution_to_dcat_us3(
        _distribution(template, "Raster tiles"),
        publisher={"@type": "Organization", "name": "Org"},
        contacts=[{"@type": "Kind", "fn": "A"}],
        license_value=None,
        landing_iri=landing,
    )
    service = out["accessService"][0]
    assert out["accessURL"] == landing
    assert service["endpointURL"] == [landing]
    assert out["description"] == f"Tile URL template: {template} Raster tiles"
    assert template in service["description"]
    assert "{" not in out["accessURL"] + service["endpointURL"][0]


def test_plain_distribution_url_is_unchanged():
    from app.standards.dcat_us.service import _distribution_to_dcat_us3

    url = "https://x.test/collections/a/items"
    out = _distribution_to_dcat_us3(
        _distribution(url),
        publisher={"@type": "Organization", "name": "Org"},
        contacts=[{"@type": "Kind", "fn": "A"}],
        license_value=None,
        landing_iri="https://x.test/datasets/abc/dcat-us/3.0",
    )
    assert out["accessURL"] == url
    assert out["accessService"][0]["endpointURL"] == [url]
    assert "description" not in out

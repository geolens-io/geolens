"""Unit tests for OGC API Records protocol helpers.

Collection license derivation. No database needed: the
helpers under test take plain dicts.
"""

from datetime import datetime, timezone

from app.modules.catalog.search.records_protocol import (
    collection_search_feature,
    derive_collection_license,
)

PDDL = "Open Data Commons PDDL 1.0"
CC_BY = "CC-BY-4.0"


def _coll(**overrides):
    coll = {
        "id": "coll-1",
        "name": "Test Collection",
        "description": "A test collection",
        "dataset_count": 0,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-03-01T00:00:00",
    }
    coll.update(overrides)
    return coll


class TestDeriveCollectionLicense:
    def test_no_licenses_is_proprietary(self):
        assert derive_collection_license(None) == "proprietary"
        assert derive_collection_license([]) == "proprietary"

    def test_blank_licenses_count_as_proprietary(self):
        assert derive_collection_license([None, ""]) == "proprietary"
        assert derive_collection_license(["", PDDL, None]) == "various"

    def test_single_license_is_used(self):
        assert derive_collection_license([PDDL]) == PDDL
        assert derive_collection_license([PDDL, PDDL]) == PDDL

    def test_mixed_licenses_are_various(self):
        assert derive_collection_license([PDDL, CC_BY]) == "various"


class TestCollectionSearchFeatureTimes:
    def test_updated_is_the_update_time_and_created_the_creation_time(self):
        properties = collection_search_feature(_coll(), "https://api.example.com")[
            "properties"
        ]

        assert properties["created"] == "2026-01-01T00:00:00"
        assert properties["updated"] == "2026-03-01T00:00:00"

    def test_datetime_values_are_written_as_iso_text(self):
        updated_at = datetime(2026, 3, 1, 12, 30, tzinfo=timezone.utc)

        properties = collection_search_feature(
            _coll(updated_at=updated_at), "https://api.example.com"
        )["properties"]

        assert properties["updated"] == "2026-03-01T12:30:00+00:00"


class TestCollectionSearchFeatureLicense:
    def test_empty_collection_is_proprietary(self):
        feature = collection_search_feature(_coll(), "https://api.example.com")

        assert feature["properties"]["license"] == "proprietary"
        assert feature["properties"]["description"] == "A test collection"

    def test_collection_without_licenses_key_is_proprietary(self):
        coll = _coll(licenses=[PDDL])
        del coll["licenses"]
        feature = collection_search_feature(coll, "https://api.example.com")

        assert feature["properties"]["license"] == "proprietary"

    def test_uniform_collection_reports_member_license(self):
        feature = collection_search_feature(
            _coll(dataset_count=2, licenses=[PDDL, PDDL]),
            "https://api.example.com",
        )

        assert feature["properties"]["license"] == PDDL
        assert feature["properties"]["description"] == "A test collection"

    def test_mixed_collection_reports_various_without_description_suffix(self):
        feature = collection_search_feature(
            _coll(dataset_count=2, licenses=[PDDL, CC_BY]),
            "https://api.example.com",
        )

        assert feature["properties"]["license"] == "various"
        assert feature["properties"]["description"] == "A test collection"

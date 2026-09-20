"""Publication decisions for staged service refreshes."""

from app.platform.refresh.verification import (
    canonical_service_source_binding_fingerprint,
    verify_service_refresh,
)


def _diff(**overrides):
    value = {
        "columns_added": [],
        "columns_removed": [],
        "type_changes": [],
        "row_count_old": 10,
        "row_count_new": 10,
        "row_count_delta": 0,
    }
    value.update(overrides)
    return value


def _verify(**overrides):
    kwargs = {
        "source_binding": {
            "service_type": "wfs",
            "url": "https://example.com/wfs",
            "layer_id": "roads",
        },
        "schema_diff": _diff(),
        "expected_feature_count": 10,
        "fetched_feature_count": 10,
        "content_digest": "a" * 64,
        "staged_geometry_type": "POINT",
        "staged_srid": 4326,
        "staged_coordinate_dimension": 2,
    }
    kwargs.update(overrides)
    return verify_service_refresh(**kwargs)


def test_count_mismatch_is_rejected_and_cannot_be_accepted() -> None:
    result = _verify(
        expected_feature_count=500,
        fetched_feature_count=400,
        accepted_fingerprint="anything",
        accepted_run_id="prior-run",
    )

    assert result["decision"] == "rejected"
    assert result["count_status"] == "mismatched"
    assert result["accepted_blocked_run_id"] is None


def test_missing_source_count_requires_review() -> None:
    result = _verify(expected_feature_count=None, fetched_feature_count=10)

    assert result["decision"] == "blocked"
    assert result["count_status"] == "unavailable"
    assert result["review_reasons"] == ["source_count_unavailable"]


def test_destructive_schema_change_requires_review() -> None:
    result = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}])
    )

    assert result["decision"] == "blocked"
    assert result["review_reasons"] == ["destructive_schema_change"]
    assert result["review_fingerprint"]


def test_nonempty_dataset_becoming_empty_requires_review() -> None:
    result = _verify(
        schema_diff=_diff(row_count_new=0, row_count_delta=-10),
        expected_feature_count=0,
        fetched_feature_count=0,
    )

    assert result["decision"] == "blocked"
    assert result["review_reasons"] == ["empty_result"]


def test_exact_review_fingerprint_allows_one_retry() -> None:
    blocked = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}])
    )
    accepted = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}]),
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id="prior-run",
    )

    assert accepted["decision"] == "allowed"
    assert accepted["accepted_blocked_run_id"] == "prior-run"


def test_changed_source_binding_invalidates_acceptance() -> None:
    blocked = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}])
    )
    changed = _verify(
        source_binding={
            "service_type": "wfs",
            "url": "https://example.com/other",
            "layer_id": "roads",
        },
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}]),
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id="prior-run",
    )

    assert changed["decision"] == "blocked"
    assert changed["accepted_blocked_run_id"] is None


def test_changed_staged_content_invalidates_acceptance() -> None:
    blocked = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}])
    )
    changed = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}]),
        content_digest="b" * 64,
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id="prior-run",
    )

    assert changed["decision"] == "blocked"
    assert changed["accepted_blocked_run_id"] is None


def test_changed_staged_spatial_contract_invalidates_acceptance() -> None:
    blocked = _verify(
        schema_diff=_diff(columns_removed=[{"name": "zoning_code", "type": "text"}])
    )

    for changed in (
        _verify(
            schema_diff=_diff(
                columns_removed=[{"name": "zoning_code", "type": "text"}]
            ),
            staged_geometry_type="POLYGON",
            accepted_fingerprint=blocked["review_fingerprint"],
            accepted_run_id="prior-run",
        ),
        _verify(
            schema_diff=_diff(
                columns_removed=[{"name": "zoning_code", "type": "text"}]
            ),
            staged_coordinate_dimension=3,
            accepted_fingerprint=blocked["review_fingerprint"],
            accepted_run_id="prior-run",
        ),
        _verify(
            schema_diff=_diff(
                columns_removed=[{"name": "zoning_code", "type": "text"}]
            ),
            staged_srid=3857,
            accepted_fingerprint=blocked["review_fingerprint"],
            accepted_run_id="prior-run",
        ),
    ):
        assert changed["decision"] == "blocked"
        assert changed["accepted_blocked_run_id"] is None


def _arcgis_id_binding(
    *, coverage_status: str = "matched", membership: str = "matched"
):
    return {
        "service_type": "arcgis_featureserver",
        "url": "https://services.example.com/FeatureServer",
        "layer_id": "0",
        "verification_policy": "arcgis_id_set_v1",
        "credential_version": "credential-version-7",
        "arcgis_id_coverage": {
            "status": coverage_status,
            "source_membership_status": membership,
            "oid_field": "OBJECTID",
            "planned_count": 3,
            "staged_distinct_count": 3,
            "missing_count": 0,
            "unexpected_count": 0,
            "duplicate_count": 0,
            "invalid_count": 0,
            "staged_id_set_digest": "b" * 64,
        },
    }


def test_exact_arcgis_id_coverage_qualifies_without_a_snapshot_claim() -> None:
    result = _verify(source_binding=_arcgis_id_binding())

    assert result["decision"] == "allowed"
    assert result["identity_check"] == "arcgis_id_set"
    assert result["source_binding"]["credential_version"] == "credential-version-7"


def test_same_count_duplicate_or_missing_arcgis_ids_are_rejected() -> None:
    result = _verify(source_binding=_arcgis_id_binding(coverage_status="mismatched"))

    assert result["decision"] == "rejected"
    assert "arcgis_id_coverage_unavailable" in result["review_reasons"]


def test_arcgis_source_membership_change_is_rejected_and_cannot_be_accepted() -> None:
    blocked = _verify(source_binding=_arcgis_id_binding(membership="changed"))
    retried = _verify(
        source_binding=_arcgis_id_binding(membership="changed"),
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id="prior-run",
    )

    assert blocked["decision"] == "rejected"
    assert retried["decision"] == "rejected"
    assert retried["accepted_blocked_run_id"] is None


def test_stronger_policy_without_arcgis_coverage_never_qualifies() -> None:
    result = _verify(
        source_binding={
            "service_type": "wfs",
            "url": "https://example.com/wfs",
            "layer_id": "roads",
            "verification_policy": "arcgis_id_set_v1",
        }
    )

    assert result["decision"] == "blocked"
    assert "arcgis_id_coverage_unavailable" in result["review_reasons"]


def test_unavailable_arcgis_membership_cannot_be_accepted_as_strong() -> None:
    blocked = _verify(source_binding=_arcgis_id_binding(membership="unavailable"))
    retried = _verify(
        source_binding=_arcgis_id_binding(membership="unavailable"),
        accepted_fingerprint=blocked["review_fingerprint"],
        accepted_run_id="prior-run",
    )

    assert blocked["decision"] == "blocked"
    assert retried["decision"] == "blocked"
    assert retried["accepted_blocked_run_id"] is None


def test_source_fingerprint_uses_only_canonical_service_identity() -> None:
    binding = _arcgis_id_binding()
    fingerprint = canonical_service_source_binding_fingerprint(binding)

    assert fingerprint == canonical_service_source_binding_fingerprint(
        {
            **binding,
            "credential_version": "rotated-version",
            "arcgis_id_coverage": {"status": "mismatched"},
        }
    )
    assert fingerprint != canonical_service_source_binding_fingerprint(
        {**binding, "layer_id": "1"}
    )

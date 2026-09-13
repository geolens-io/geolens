"""Publication decisions for staged service refreshes."""

from app.platform.refresh.verification import verify_service_refresh


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

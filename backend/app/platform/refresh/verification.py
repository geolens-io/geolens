"""Pre-publication checks for service refreshes."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_service_source_binding_fingerprint(source_binding: dict[str, Any]) -> str:
    """Fingerprint the secret-free service identity shared by runs and sync.

    Verification policy, credentials, coverage results, and arbitrary origin
    metadata are intentionally excluded. They have their own exact eligibility
    checks; mixing them into the source identity would make a credential
    rotation look like a source rebind.
    """
    service_type = source_binding.get("service_type")
    url = source_binding.get("url")
    layer_id = source_binding.get("layer_id")
    if not isinstance(service_type, str) or not service_type:
        raise ValueError("service source binding requires a connector")
    if not isinstance(url, str) or not url:
        raise ValueError("service source binding requires a URL")
    if layer_id is None or isinstance(layer_id, bool):
        raise ValueError("service source binding requires a layer identity")
    payload = {
        "connector": service_type,
        "layer_id": str(layer_id),
        "service_url": url,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def verify_service_refresh(
    *,
    source_binding: dict[str, Any],
    schema_diff: dict[str, Any],
    expected_feature_count: int | None,
    fetched_feature_count: int | None,
    content_digest: str,
    staged_geometry_type: str | None,
    staged_srid: int | None,
    staged_coordinate_dimension: int | None,
    accepted_fingerprint: str | None = None,
    accepted_run_id: str | None = None,
) -> dict[str, Any]:
    """Return durable evidence and a publication decision for a staged fetch."""
    if expected_feature_count is None:
        count_status = "unavailable"
    elif fetched_feature_count == expected_feature_count:
        count_status = "matched"
    else:
        count_status = "mismatched"

    review_reasons: list[str] = []
    id_coverage = source_binding.get("arcgis_id_coverage")
    strong_arcgis_policy = (
        source_binding.get("verification_policy") == "arcgis_id_set_v1"
    )
    coverage_status = (
        id_coverage.get("status") if isinstance(id_coverage, dict) else "unavailable"
    )
    membership_status = (
        id_coverage.get("source_membership_status")
        if isinstance(id_coverage, dict)
        else "unavailable"
    )
    if expected_feature_count is None:
        review_reasons.append("source_count_unavailable")
    if fetched_feature_count == 0 and schema_diff.get("row_count_old", 0) != 0:
        review_reasons.append("empty_result")
    if schema_diff.get("columns_removed") or schema_diff.get("type_changes"):
        review_reasons.append("destructive_schema_change")
    if strong_arcgis_policy and coverage_status != "matched":
        review_reasons.append("arcgis_id_coverage_unavailable")
    if strong_arcgis_policy and membership_status != "matched":
        review_reasons.append("arcgis_source_membership_changed")

    fingerprint_payload = {
        "source_binding": source_binding,
        "schema_diff": schema_diff,
        "expected_feature_count": expected_feature_count,
        "fetched_feature_count": fetched_feature_count,
        "content_digest": content_digest,
        "staged_geometry_type": staged_geometry_type,
        "staged_srid": staged_srid,
        "staged_coordinate_dimension": staged_coordinate_dimension,
        "review_reasons": review_reasons,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()

    exact_arcgis_membership = (
        coverage_status == "matched" and membership_status == "matched"
    )
    accepted = bool(
        review_reasons
        and accepted_fingerprint
        and accepted_fingerprint == fingerprint
        and (not strong_arcgis_policy or exact_arcgis_membership)
    )
    hard_id_failure = strong_arcgis_policy and (
        coverage_status == "mismatched" or membership_status == "changed"
    )
    if count_status == "mismatched" or hard_id_failure:
        decision = "rejected"
    elif review_reasons and not accepted:
        decision = "blocked"
    else:
        decision = "allowed"

    return {
        "decision": decision,
        "source_binding": source_binding,
        "source_binding_fingerprint": canonical_service_source_binding_fingerprint(
            source_binding
        ),
        "source_count": expected_feature_count,
        "fetched_count": fetched_feature_count,
        "count_status": count_status,
        "identity_check": "arcgis_id_set" if strong_arcgis_policy else "content_digest",
        "arcgis_id_coverage": id_coverage if strong_arcgis_policy else None,
        "content_digest": content_digest,
        "staged_geometry_type": staged_geometry_type,
        "staged_srid": staged_srid,
        "staged_coordinate_dimension": staged_coordinate_dimension,
        "review_reasons": review_reasons,
        "review_fingerprint": fingerprint if review_reasons else None,
        "accepted_blocked_run_id": (
            accepted_run_id if accepted and decision == "allowed" else None
        ),
    }

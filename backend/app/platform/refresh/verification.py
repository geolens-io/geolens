"""Pre-publication checks for service refreshes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

_GEOMETRY_FAMILIES = {
    "POINT": "point",
    "MULTIPOINT": "point",
    "LINESTRING": "line",
    "MULTILINESTRING": "line",
    "POLYGON": "polygon",
    "MULTIPOLYGON": "polygon",
    "GEOMETRYCOLLECTION": "collection",
}


@dataclass(frozen=True, slots=True)
class GeometryContract:
    """The geometry facts a refresh is compared on; ``None`` means unknown."""

    family: str | None
    srid: int | None
    is_3d: bool | None
    n_dims: int | None


def geometry_contract(
    *,
    geometry_type: str | None,
    srid: int | None,
    is_3d: bool | None,
    n_dims: int | None,
) -> GeometryContract:
    """Fold a catalog geometry type into a family; generic types are unknown."""
    family = _GEOMETRY_FAMILIES.get((geometry_type or "").upper())
    return GeometryContract(family=family, srid=srid, is_3d=is_3d, n_dims=n_dims)


def review_reasons(
    *,
    schema_diff: dict[str, Any],
    fetched_feature_count: int | None,
    live: GeometryContract,
    staged: GeometryContract,
) -> list[str]:
    """Return the review reasons every refresh strategy shares, in order.

    A fact unknown on either side is not compared, and single/multi within one
    family or a gain in dimension never needs review.
    """
    reasons: list[str] = []
    if fetched_feature_count == 0 and schema_diff.get("row_count_old", 0) != 0:
        reasons.append("empty_result")
    if schema_diff.get("columns_removed") or schema_diff.get("type_changes"):
        reasons.append("destructive_schema_change")
    if live.family and staged.family and live.family != staged.family:
        reasons.append("geometry_type_changed")
    if live.srid is not None and staged.srid is not None and live.srid != staged.srid:
        reasons.append("srid_changed")
    lost_z = live.is_3d is True and staged.is_3d is False
    fewer_dims = (
        live.n_dims is not None
        and staged.n_dims is not None
        and staged.n_dims < live.n_dims
    )
    if lost_z or fewer_dims:
        reasons.append("coordinate_dimension_reduced")
    return reasons


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
    live: GeometryContract,
    staged: GeometryContract,
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

    reasons: list[str] = []
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
        reasons.append("source_count_unavailable")
    reasons.extend(
        review_reasons(
            schema_diff=schema_diff,
            fetched_feature_count=fetched_feature_count,
            live=live,
            staged=staged,
        )
    )
    if strong_arcgis_policy and coverage_status != "matched":
        reasons.append("arcgis_id_coverage_unavailable")
    if strong_arcgis_policy and membership_status != "matched":
        reasons.append("arcgis_source_membership_changed")

    geometry_evidence = {"live": asdict(live), "staged": asdict(staged)}
    fingerprint_payload = {
        "source_binding": source_binding,
        "schema_diff": schema_diff,
        "expected_feature_count": expected_feature_count,
        "fetched_feature_count": fetched_feature_count,
        "content_digest": content_digest,
        "staged_geometry_type": staged_geometry_type,
        "staged_srid": staged_srid,
        "staged_coordinate_dimension": staged_coordinate_dimension,
        "review_reasons": reasons,
        "geometry_contract": geometry_evidence,
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
        reasons
        and accepted_fingerprint
        and accepted_fingerprint == fingerprint
        and (not strong_arcgis_policy or exact_arcgis_membership)
    )
    hard_id_failure = strong_arcgis_policy and (
        coverage_status == "mismatched" or membership_status == "changed"
    )
    if count_status == "mismatched" or hard_id_failure:
        decision = "rejected"
    elif reasons and not accepted:
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
        "review_reasons": reasons,
        "geometry_contract": geometry_evidence,
        "review_fingerprint": fingerprint if reasons else None,
        "accepted_blocked_run_id": (
            accepted_run_id if accepted and decision == "allowed" else None
        ),
    }


def refresh_rejection_diagnostic(verification: dict[str, Any]) -> tuple[str, str]:
    """Describe the highest-priority hard verification failure."""
    if verification.get("count_status") == "mismatched":
        return (
            "source_count_mismatch",
            "The staged row count did not match the source count.",
        )

    coverage = verification.get("arcgis_id_coverage")
    if isinstance(coverage, dict):
        if coverage.get("status") == "mismatched":
            return (
                "arcgis_id_coverage_mismatch",
                "The staged ArcGIS object IDs did not match the source IDs.",
            )
        if coverage.get("source_membership_status") == "changed":
            return (
                "arcgis_source_membership_changed",
                "The ArcGIS source membership changed during refresh.",
            )

    return (
        "refresh_verification_rejected",
        "Refresh verification rejected publication.",
    )

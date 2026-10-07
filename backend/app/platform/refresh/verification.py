"""Pre-publication checks for service refreshes and file replacements."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

# Why a held file replacement can no longer be accepted: its acceptance would
# publish an upload over data that replaced what the run was compared with.
REVIEW_SUPERSEDED = (
    "The dataset changed after this replacement was held. Upload the file again."
)

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
    """The geometry facts a refresh is compared on; ``None`` means unknown.

    ``families`` is an empty set when a table with a geometry column was
    measured and holds no usable geometry.
    """

    families: frozenset[str] | None
    srid: int | None
    is_3d: bool | None
    n_dims: int | None


def geometry_contract(
    *,
    geometry_types: Iterable[str] | None,
    srid: int | None,
    is_3d: bool | None,
    n_dims: int | None,
) -> GeometryContract:
    """Fold the distinct geometry types a table holds into a set of families.

    Single and multi fold together and the generic type is dropped. ``None``
    types, or only types with no family, leave the families unknown; an empty
    list is a measurement of no geometry at all.
    """
    if geometry_types is None:
        return GeometryContract(families=None, srid=srid, is_3d=is_3d, n_dims=n_dims)
    types = list(geometry_types)
    families = frozenset(
        family
        for geometry_type in types
        if (family := _GEOMETRY_FAMILIES.get(geometry_type.upper()))
    )
    return GeometryContract(
        families=None if types and not families else families,
        srid=srid,
        is_3d=is_3d,
        n_dims=n_dims,
    )


def _has_m(contract: GeometryContract) -> bool | None:
    """Whether the contract carries M ordinates, or ``None`` when it can't tell."""
    if contract.n_dims == 4:
        return True
    if contract.n_dims == 2:
        return False
    if contract.n_dims == 3 and contract.is_3d is not None:
        return not contract.is_3d
    return None


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
    # A staged table with no rows is empty_result's to report.
    staged_families = (
        None
        if staged.families == frozenset() and fetched_feature_count == 0
        else staged.families
    )
    if (
        live.families
        and staged_families is not None
        and live.families != staged_families
    ):
        reasons.append("geometry_type_changed")
    if live.srid is not None and staged.srid is not None and live.srid != staged.srid:
        reasons.append("srid_changed")
    lost_z = live.is_3d is True and staged.is_3d is False
    fewer_dims = (
        live.n_dims is not None
        and staged.n_dims is not None
        and staged.n_dims < live.n_dims
    )
    lost_m = _has_m(live) is True and _has_m(staged) is False
    if lost_z or fewer_dims or lost_m:
        reasons.append("coordinate_dimension_reduced")
    return reasons


_GEOMETRY_REASONS = frozenset(
    {"geometry_type_changed", "srid_changed", "coordinate_dimension_reduced"}
)

LIVE_DATA_CHANGED = "live_data_changed"

# The baseline of a replacement whose start predates the count, so every write
# counts as later.
UNKNOWN_DATA_REVISION = -1


def live_data_revision(baseline: int | None, current: int | None) -> int | None:
    """``current`` when the live table was written since ``baseline``, else None.

    A replacement admitted before the dataset counted its writes has no
    baseline and is not compared.
    """
    if baseline is None or current is None or current == baseline:
        return None
    return current


def declared_geometry_contract(
    declared_type: str | None, *, srid: int | None
) -> GeometryContract:
    """The contract a file's declared layer type implies, before it is loaded.

    ``declared_type`` is ogrinfo's spelling, such as ``MultiPolygonZ``. A
    generic or unknown type gives no families, and the dimension count is
    never taken from the declaration.
    """
    if not declared_type:
        return GeometryContract(families=None, srid=None, is_3d=None, n_dims=None)
    base = declared_type.upper().replace(" ", "")
    has_z = base.endswith(("Z", "ZM"))
    contract = geometry_contract(
        geometry_types=[base.removesuffix("M").removesuffix("Z")],
        srid=srid,
        is_3d=True,
        n_dims=None,
    )
    # A generic type without a Z suffix says nothing about its coordinates.
    is_3d = True if has_z else (False if contract.families else None)
    return GeometryContract(
        families=contract.families, srid=srid, is_3d=is_3d, n_dims=None
    )


def _contract_facts(contract: GeometryContract) -> list[Any]:
    return [sorted(contract.families or ()), contract.srid, contract.is_3d]


def review_subject(
    reasons: list[str],
    schema_diff: dict[str, Any],
    live: GeometryContract,
    staged: GeometryContract,
) -> dict[str, Any]:
    """What a person reviewing a file replacement is shown and acknowledges.

    Counts, added columns and file identity are left out: a preview cannot
    see them the way the worker does.
    """
    subject: dict[str, Any] = {
        "reasons": sorted(reasons),
        "columns_removed": sorted(
            column["name"].lower()
            for column in schema_diff.get("columns_removed") or ()
        ),
        "type_changes": sorted(
            [change["name"].lower(), change["old_type"], change["new_type"]]
            for change in schema_diff.get("type_changes") or ()
        ),
    }
    if _GEOMETRY_REASONS.intersection(reasons):
        subject["geometry"] = {
            "live": _contract_facts(live),
            "staged": _contract_facts(staged),
        }
    return subject


def review_fingerprint(subject: dict[str, Any]) -> str | None:
    """The sha256 of the subject's canonical JSON, or ``None`` when nothing needs review."""
    if not subject["reasons"]:
        return None
    return hashlib.sha256(
        json.dumps(
            subject, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _geometry_evidence(
    live: GeometryContract, staged: GeometryContract
) -> dict[str, dict[str, Any]]:
    return {
        side: {**asdict(contract), "families": sorted(contract.families or ())}
        for side, contract in (("live", live), ("staged", staged))
    }


def verify_file_replacement(
    *,
    schema_diff: dict[str, Any],
    fetched_feature_count: int | None,
    live: GeometryContract,
    staged: GeometryContract,
    source_binding: dict[str, Any],
    reviewed_fingerprint: str | None,
    accepted_fingerprint: str | None,
    accepted_run_id: str | None,
    data_revision_baseline: int | None = None,
    data_revision: int | None = None,
) -> dict[str, Any]:
    """Return the evidence and decision for a staged file replacement.

    A replacement with review reasons publishes only when a client sent the
    fingerprint of the subject it showed, or a person accepted a blocked run
    with the same subject. When the live table was written since
    ``data_revision_baseline``, the subject names the revision found, so an
    acceptance covers only the writes its run saw. A file run is never
    rejected.
    """
    reasons = review_reasons(
        schema_diff=schema_diff,
        fetched_feature_count=fetched_feature_count,
        live=live,
        staged=staged,
    )
    changed = live_data_revision(data_revision_baseline, data_revision)
    if changed is not None:
        reasons.append(LIVE_DATA_CHANGED)
    subject = review_subject(reasons, schema_diff, live, staged)
    if changed is not None:
        subject["data_revision"] = changed
    fingerprint = review_fingerprint(subject)
    acknowledged_by = None
    if fingerprint is not None and reviewed_fingerprint == fingerprint:
        acknowledged_by = "preview"
    elif fingerprint is not None and accepted_fingerprint == fingerprint:
        acknowledged_by = "accepted_run"
    return {
        "decision": "blocked" if reasons and acknowledged_by is None else "allowed",
        "source_binding": source_binding,
        "source_binding_fingerprint": None,
        "source_count": None,
        "fetched_count": fetched_feature_count,
        "count_status": "unavailable",
        "identity_check": "unavailable",
        "review_reasons": reasons,
        "geometry_contract": _geometry_evidence(live, staged),
        "review_fingerprint": fingerprint,
        "review_acknowledged_by": acknowledged_by,
        "accepted_blocked_run_id": (
            accepted_run_id if acknowledged_by == "accepted_run" else None
        ),
        "data_revision_baseline": data_revision_baseline,
        "data_revision": data_revision,
    }


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
    data_revision_baseline: int | None = None,
    data_revision: int | None = None,
) -> dict[str, Any]:
    """Return durable evidence and a publication decision for a staged fetch.

    A write to the live table since ``data_revision_baseline`` is a review
    reason, and the fingerprint names the revision found.
    """
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
    changed = live_data_revision(data_revision_baseline, data_revision)
    if changed is not None:
        reasons.append(LIVE_DATA_CHANGED)

    geometry_evidence = _geometry_evidence(live, staged)
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
    if changed is not None:
        fingerprint_payload["data_revision"] = changed
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
        "data_revision_baseline": data_revision_baseline,
        "data_revision": data_revision,
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

"""Pre-publication checks for service refreshes."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def verify_service_refresh(
    *,
    source_binding: dict[str, Any],
    schema_diff: dict[str, Any],
    expected_feature_count: int | None,
    fetched_feature_count: int | None,
    content_digest: str,
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
    if expected_feature_count is None:
        review_reasons.append("source_count_unavailable")
    if fetched_feature_count == 0 and schema_diff.get("row_count_old", 0) != 0:
        review_reasons.append("empty_result")
    if schema_diff.get("columns_removed") or schema_diff.get("type_changes"):
        review_reasons.append("destructive_schema_change")

    fingerprint_payload = {
        "source_binding": source_binding,
        "schema_diff": schema_diff,
        "expected_feature_count": expected_feature_count,
        "fetched_feature_count": fetched_feature_count,
        "content_digest": content_digest,
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

    accepted = bool(
        review_reasons and accepted_fingerprint and accepted_fingerprint == fingerprint
    )
    if count_status == "mismatched":
        decision = "rejected"
    elif review_reasons and not accepted:
        decision = "blocked"
    else:
        decision = "allowed"

    return {
        "decision": decision,
        "source_binding": source_binding,
        "source_count": expected_feature_count,
        "fetched_count": fetched_feature_count,
        "count_status": count_status,
        "identity_check": "content_digest",
        "content_digest": content_digest,
        "review_reasons": review_reasons,
        "review_fingerprint": fingerprint if review_reasons else None,
        "accepted_blocked_run_id": accepted_run_id if accepted else None,
    }

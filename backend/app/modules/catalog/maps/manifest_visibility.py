"""Who a manifest map is visible to: the rules a manifest dataset's
visibility follows, and a public map's datasets."""

from __future__ import annotations

from typing import Any

from app.core.processing_port import PendingManifestDataset
from app.modules.catalog.maps.manifest_messages import (
    OTHER_REFUSAL,
    PUBLIC_REFUSED,
    SHARING_KEPT,
    message,
    short,
)
from app.platform.record_audience import (
    PublicationRefused,
    audience_phrase,
    effective_publication,
)

# A map has no record status: a public map is open to anonymous readers, as
# a public and published dataset is.
_MAP_STATUS = "published"
_PUBLIC_REFUSALS = {
    "key": (
        "A publish key can't make anything public",
        "Use Organization, or sign in.",
    ),
    "restriction": (
        "Public visibility is restricted on this server",
        "Use Organization, or ask the admin.",
    ),
    "datasets": (
        "A public map can't show datasets that aren't public",
        "Share the datasets publicly in GeoLens, or use Organization.",
    ),
}


def planned_public(dataset: Any, planned: PendingManifestDataset | None) -> bool:
    """Whether a layer's dataset is public and published once the request's
    own entry for it, ``planned``, has published it."""
    if planned is None:
        return dataset is not None and dataset.public
    visibility = (
        planned.visibility or (dataset.visibility if dataset else None) or "private"
    )
    return (visibility, planned.record_status) == ("public", "published")


def public_refused(entry: Any, severity: str, reason: str) -> dict[str, Any]:
    refusal, fix = _PUBLIC_REFUSALS[reason]
    outcome = (
        "was not published"
        if severity == "error"
        else "is shared with the organization instead"
    )
    return message(
        PUBLIC_REFUSED,
        severity,
        f"{refusal}, so the map {short(entry.name)!r} {outcome}.",
        fix=fix,
    )


def judge_visibility(
    entry: Any,
    now: str | None,
    shows_non_public: bool,
    *,
    public_fallback: str | None,
    may_set_public: bool,
    is_key: bool,
) -> tuple[str | None, list[dict[str, Any]]]:
    """The visibility a map's apply writes (None keeps the map's) and its
    messages, by the rules a manifest dataset's visibility follows.

    A public map that would show a dataset that isn't public and published is
    refused as public is, and so falls back like it. A publish key asking
    for a wider level keeps the map's, with warning A056.
    """
    try:
        publication = effective_publication(
            entry.visibility,
            _MAP_STATUS,
            public_fallback,
            may_set_public=may_set_public,
            is_key=is_key,
            now=None if now is None else (now, _MAP_STATUS),
        )
    except PublicationRefused as refused:
        if refused.reason == "widening":
            return None, [
                message(
                    OTHER_REFUSAL,
                    "error",
                    "A publish key can't widen a map's visibility.",
                    fix="Keep the current Sharing level, or sign in.",
                )
            ]
        return None, [public_refused(entry, "error", refused.reason)]
    if publication.widening_refused:
        level = "internal" if entry.visibility == "public" else entry.visibility
        return None, [
            message(
                SHARING_KEPT,
                "warning",
                f"A publish key can't share the map {short(entry.name)!r} with "
                f"more people, so it keeps its current Sharing level: "
                f"{audience_phrase(str(level))} won't see it unless they "
                "already can.",
                fix="Share the map in GeoLens, or sign in.",
            )
        ]
    visibility, fell_back_for = publication.visibility, publication.fell_back_for
    if (visibility or now or "private") == "public" and shows_non_public:
        if public_fallback != "internal":
            return None, [public_refused(entry, "error", "datasets")]
        visibility, fell_back_for = "internal", "datasets"
    messages = []
    if fell_back_for is not None:
        messages.append(public_refused(entry, "warning", fell_back_for))
    return visibility, messages

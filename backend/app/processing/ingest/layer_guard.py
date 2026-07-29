"""Request-level layer_name validation for the ingest endpoints.

fix(#823): a user-supplied ``layer_name`` (preview query param, vector commit
body, fan-out request) is forwarded to GDAL argv as a positional token. The
argv-level backstop lives in ``ogr.validate_layer_name_argv``; these helpers
give the router endpoints clear 4xx responses before any job state changes.

Kept out of ``router.py`` to respect the Phase 276 CODE-01 router LOC cap
(decomposition preferred over allowlist growth).
"""

from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob


def reject_option_like_layer_name(layer_name: str | None) -> None:
    """422 for layer names starting with '-' (argument-injection hygiene)."""
    if isinstance(layer_name, str) and layer_name.startswith("-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid layer_name: must not start with '-'",
        )


def known_layer_names(job: "IngestJob") -> set[str]:
    """Normalise job.user_metadata['all_layers'] to a set of layer-name strings.

    all_layers may be a list of dicts ({name: str, ...}) or a list of strings
    depending on how the preview stored them. Returns an empty set when the
    preview recorded no layer list (single-layer sources).
    """
    all_layers: list = (job.user_metadata or {}).get("all_layers") or []
    if all_layers and isinstance(all_layers[0], dict):
        return {lay.get("name", "") for lay in all_layers}
    return set(all_layers)


def validate_commit_layer_name(job: "IngestJob", layer_name: object) -> None:
    """Guard the single-layer commit endpoint's layer_name (fix(#823)).

    The value is stored in user_metadata and later reaches the worker's
    ogr2ogr argv — unlike the fan-out endpoint, it previously had no
    validation. Rejects option-like names outright and names absent from the
    preview's all_layers when that list exists (single-layer sources never
    record all_layers, so they get the dash guard only; the argv-level guard
    in ogr.py backstops the worker regardless).
    """
    if not isinstance(layer_name, str) or not layer_name:
        return
    reject_option_like_layer_name(layer_name)
    known = known_layer_names(job)
    if known and layer_name not in known:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Unknown layer name — not found in the uploaded file",
                "unknown_layers": [layer_name],
                "available_layers": sorted(known),
            },
        )

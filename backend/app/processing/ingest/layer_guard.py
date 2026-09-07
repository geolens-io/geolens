"""Request-level layer_name validation for the ingest endpoints.

fix(#823): a user-supplied ``layer_name`` (preview query param, vector commit
body, fan-out request) reaches GDAL argv as a positional token. These helpers
give the router endpoints clear 4xx responses before any job state changes;
the argv-level backstop is ``ogr.validate_layer_name_argv``.
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

    Entries may be dicts ({name: str, ...}) or plain strings. Empty when the
    preview recorded no layer list (single-layer sources).
    """
    all_layers: list = (job.user_metadata or {}).get("all_layers") or []
    if all_layers and isinstance(all_layers[0], dict):
        return {lay.get("name", "") for lay in all_layers}
    return set(all_layers)


def validate_commit_layer_name(job: "IngestJob", layer_name: object) -> None:
    """Guard the single-layer commit endpoint's layer_name (fix(#823)).

    Rejects option-like names outright, and names absent from the preview's
    all_layers when that list exists. Sources with no all_layers get the
    dash guard only; ogr.py's argv-level guard backstops the worker regardless.
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

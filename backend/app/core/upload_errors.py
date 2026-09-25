"""The refusal an upload's own content earns, in a module every layer may import.

fix(#1846): raised where content is inspected
(``processing/ingest/validation.py``) but caught where the refusal becomes a
response, including ``modules/catalog/datasets/api/router_reupload.py`` —
which may not import ``app.processing.*`` (``tests/test_layering.py``). Lives
in ``core/`` since an exception type is cross-cutting and carries no logic
from either domain.

Every refusal also carries a stable ``code`` and the ``values`` its message
interpolated, so the frontend can translate it. ``code`` is required, since
``tests/test_upload_refusal_codes.py`` discovers refusals by walking these
constructions.
"""

from collections.abc import Mapping

#: fix(#2031): one wording for the two doors that can see the loss coming.
_GEOMETRY_LOSS_MESSAGE = (
    "The replacement has no geometry, and this dataset stores geometry. "
    "Replacing it would leave the dataset a plain table, so nothing was "
    "changed. Import the file as a new dataset instead."
)


def geometry_loss_refusal(
    *,
    record_type: str | None,
    dataset_geometry_type: str | None,
    source_has_geometry: bool,
) -> str | None:
    """The refusal when a replacement would strip a vector dataset's geometry.

    fix(#2031): a geometry-less CSV over a vector dataset committed with no
    warning and reclassified it ``table`` — the cross-record-type swap the
    re-upload doors already refuse when they can read it off an extension.

    Both dataset facts are read: ``record_type`` is derived from the measured
    geometry on every write, but the two can disagree on a never-measured
    dataset, and one with no geometry recorded has none to lose.
    """
    if record_type != "vector_dataset" or dataset_geometry_type is None:
        return None
    if source_has_geometry:
        return None
    return _GEOMETRY_LOSS_MESSAGE


class CodedRefusal(ValueError):
    """A refusal carrying a stable ``code`` and the ``values`` its message
    interpolated, for a door to put on the wire instead of raw English.
    """

    def __init__(
        self, message: str, *, code: str, values: Mapping[str, str | int] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.values: dict[str, str | int] = dict(values) if values else {}


class IngestCeilingError(CodedRefusal):
    """A refusal whose text names an ingest ceiling, the value, and the way out.

    fix(#2043): a marker base, mixed into ``processing.ingest.ogr.
    IngestBudgetExceededError`` so that class stays an ``IngestionError`` for
    the worker while the re-upload preview, which may not import
    ``app.processing.*``, can still catch it and pass its text through.
    """


class UnsafeUploadError(CodedRefusal):
    """An upload refused for what its content instructs, not for its shape.

    Its own class so endpoints that swallow GDAL errors behind a generic
    message can still let this server-authored text through.
    """


#: The code a door falls back to for a content refusal it still catches
#: broadly (``except ValueError``), for a library exception that never went
#: through ``CodedRefusal``.
_UNCODED_REFUSAL_FALLBACK_CODE = "unsafe_upload_content"


def refusal_detail(exc: Exception) -> dict[str, str | int]:
    """The HTTPException ``detail`` built from a ``CodedRefusal``.

    Falls back to the code above for a plain ``ValueError`` a door still
    catches broadly but that never went through ``CodedRefusal``.
    """
    code = getattr(exc, "code", None) or _UNCODED_REFUSAL_FALLBACK_CODE
    values = getattr(exc, "values", None) or {}
    return {"code": code, "message": str(exc), **values}


class CodedUploadError(UnsafeUploadError):
    """An ``UnsafeUploadError`` built code first, as the point cloud checks raise it."""

    def __init__(self, code: str, message: str, **values: str | int) -> None:
        super().__init__(message, code=code, values=values)

"""The refusal an upload's own content earns, in a module every layer may import.

fix(#1846): raised where content is inspected
(``processing/ingest/validation.py``) but caught where the refusal becomes a
response, including ``modules/catalog/datasets/api/router_reupload.py`` —
which may not import ``app.processing.*`` (``tests/test_layering.py``). Lives
in ``core/`` since an exception type is cross-cutting and carries no logic
from either domain.
"""

#: fix(#2031): one wording for the two doors that can see the loss coming.
_GEOMETRY_LOSS_MESSAGE = (
    "The replacement has no geometry, and this dataset stores geometry. "
    "Replacing it would leave the dataset a plain table, so nothing was "
    "changed. Import the file as a new dataset instead."
)


def geometry_loss_refusal(
    *, record_type: str | None, source_has_geometry: bool
) -> str | None:
    """The refusal when a replacement would strip a vector dataset's geometry.

    fix(#2031): a geometry-less CSV over a vector dataset committed with no
    warning and reclassified it ``table`` — the cross-record-type swap the
    re-upload doors already refuse when they can read it off an extension.
    """
    if record_type == "vector_dataset" and not source_has_geometry:
        return _GEOMETRY_LOSS_MESSAGE
    return None


class IngestCeilingError(Exception):
    """A refusal whose text names an ingest ceiling, the value, and the way out.

    fix(#2043): a marker base, mixed into ``processing.ingest.ogr.
    IngestBudgetExceededError`` so that class stays an ``IngestionError`` for
    the worker while the re-upload preview, which may not import
    ``app.processing.*``, can still catch it and pass its text through.
    """


class UnsafeUploadError(ValueError):
    """An upload refused for what its content instructs, not for its shape.

    A ``ValueError`` so existing doors keep mapping it to the same 4xx as
    other validation failures; its own class so endpoints that swallow GDAL
    errors behind a generic message can still let this server-authored text
    through.
    """

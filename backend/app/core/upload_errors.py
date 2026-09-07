"""The refusal an upload's own content earns, in a module every layer may import.

fix(#1846): raised where content is inspected
(``processing/ingest/validation.py``) but caught where the refusal becomes a
response, including ``modules/catalog/datasets/api/router_reupload.py`` —
which may not import ``app.processing.*`` (``tests/test_layering.py``). Lives
in ``core/`` since an exception type is cross-cutting and carries no logic
from either domain.
"""


class UnsafeUploadError(ValueError):
    """An upload refused for what its content instructs, not for its shape.

    A ``ValueError`` so existing doors keep mapping it to the same 4xx as
    other validation failures; its own class so endpoints that swallow GDAL
    errors behind a generic message can still let this server-authored text
    through.
    """

"""The refusal an upload's own content earns, in a module every layer may import.

fix(#1846 review round 4): ``UnsafeUploadError`` is raised where the content is
inspected (``processing/ingest/validation.py``) and has to be caught where the
refusal is turned into a response. One of those places is
``modules/catalog/datasets/api/router_reupload.py``, and ``modules/catalog/``
may not import ``app.processing.*`` (``tests/test_layering.py``). An exception
type is cross-cutting and carries no logic from either domain, so it lives in
``core/`` and both sides import it from here -- the same reasoning AGENTS.md
Rule 2 records for keeping ``security.py`` in ``platform/``.
"""


class UnsafeUploadError(ValueError):
    """An upload refused for what its content instructs, not for its shape.

    A ``ValueError`` so every existing door keeps mapping it to the 4xx it
    already maps validation failures to; its own class so the endpoints that
    swallow GDAL errors behind a generic message can let this one's text
    through, which is server-authored and names the fix.
    """

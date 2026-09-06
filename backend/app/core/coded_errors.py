"""A validator refusal that carries the error code its response publishes.

In ``core/`` for the reason ``upload_errors.py`` is: the raiser lives in
``platform/``, the renderer in ``standards/``, and neither may import the other.
"""


class CodedValueError(ValueError):
    """A field refusal whose ``code`` reaches the body beside its ``message``.

    ``message`` is published, so it states the policy and never the rejected
    value. Pydantic keeps the raised instance under ``ctx["error"]``, which is
    where the 422 handler reads the code back.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

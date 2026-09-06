"""A validator refusal that carries the error code its response publishes.

In ``core/`` because it is layer-neutral: the raiser is in ``platform/``, the
renderer in ``standards/``, and the type carries no logic from either.
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

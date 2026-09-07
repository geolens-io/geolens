"""A validator refusal that carries the error code its response publishes.

Layer-neutral: the raiser is in ``platform/``, the renderer in ``standards/``.
"""


class CodedValueError(ValueError):
    """A field refusal whose ``code`` reaches the body beside its ``message``.

    ``message`` is published: state the policy, never the rejected value.
    Pydantic keeps the instance under ``ctx["error"]``, where the 422 handler
    reads ``code`` back.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

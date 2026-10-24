"""An optional absolute monotonic deadline shared by one notification fan-out."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_send_deadline: ContextVar[float | None] = ContextVar(
    "notification_send_deadline", default=None
)


@contextmanager
def notification_deadline(deadline: float | None = None) -> Iterator[None]:
    """Scope a total send deadline without changing sink/channel call signatures.

    None leaves sends unbounded by a total deadline. Nested scopes restore
    their caller's deadline on completion, failure and cancellation.
    """
    token = _send_deadline.set(deadline)
    try:
        yield
    finally:
        _send_deadline.reset(token)

"""Shared SQLAlchemy declarative base.

Re-exports the single `Base` class that every ORM model in the codebase inherits
from. Domain models live in their respective feature packages (e.g.
`app.datasets.models`, `app.maps.models`) — this package only holds the base.
"""

from app.models.base import Base

__all__ = ["Base"]

"""The opt-in that lets a client read the ``restricted`` map visibility.

Clients generated before maps had ``restricted`` reject a visibility value
they don't know. For one minor release, a map response therefore names
``restricted`` only to a client that sends ``X-GeoLens-Map-Visibility:
restricted``; any other client reads such a map as ``private``.
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request, Response

MAP_VISIBILITY_HEADER = "X-GeoLens-Map-Visibility"
MAP_VISIBILITY_OPT_IN = "restricted"

_opted_in: ContextVar[bool] = ContextVar("map_visibility_opted_in", default=False)


async def map_visibility_contract(request: Request, response: Response) -> None:
    """Route dependency: read the opt-in for this request and declare that the
    response varies on it."""
    value = request.headers.get(MAP_VISIBILITY_HEADER, "")
    _opted_in.set(value.strip().lower() == MAP_VISIBILITY_OPT_IN)
    response.headers["Vary"] = MAP_VISIBILITY_HEADER


def restricted_map_visibility_opted_in() -> bool:
    """Whether this request's client reads ``restricted`` map visibility."""
    return _opted_in.get()


def stored_map_visibilities(requested: str) -> tuple[str, ...]:
    """The stored visibilities a list filter on ``requested`` matches, so a
    client that reads restricted maps as private finds them under private."""
    if requested == "private" and not restricted_map_visibility_opted_in():
        return ("private", "restricted")
    return (requested,)

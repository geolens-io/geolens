"""Web map field names as the matched dataset stores them.

An imported service's fields are stored under the names ingest gives them
(lower-cased, with reserved names renamed), and feature properties are
matched by exact name, so a renderer, label, popup or filter must use the
stored name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.loss import LossReport
from app.platform.column_names import stored_column_names


class FieldNames:
    """Resolves field names against one dataset's columns, reporting misses once.

    With no columns known every name is kept as it is.
    """

    def __init__(
        self,
        columns: Sequence[Mapping[str, Any]] | None,
        path: str = "",
        loss: LossReport | None = None,
    ) -> None:
        cols = [c for c in columns or () if isinstance(c, Mapping)]
        names = [c.get("name") for c in cols]
        self._columns = {name for name in names if isinstance(name, str)}
        sources = [(c.get("source_name"), c.get("name")) for c in cols]
        self._sourced = bool(sources) and all(
            isinstance(s, str) and isinstance(n, str) for s, n in sources
        )
        self._by_source: dict[str, set[str]] = {}
        self._by_source_folded: dict[str, set[str]] = {}
        if self._sourced:
            for source, stored in sources:
                self._by_source.setdefault(source, set()).add(stored)
                self._by_source_folded.setdefault(source.casefold(), set()).add(stored)
        self._folded: dict[str, set[str]] = {}
        for name in self._columns:
            self._folded.setdefault(name.casefold(), set()).add(name)
        self._path = path
        self._loss = loss
        self._reported: set[str] = set()

    def stored(self, name: str) -> str | None:
        """The column *name* is stored as: the column whose source field it is
        when the columns record source names (an ambiguous match is None),
        else the same name, the name ingest gives the field, or the one
        column equal to it ignoring case."""
        if not self._columns:
            return name
        if self._sourced:
            for found in (
                self._by_source.get(name),
                self._by_source_folded.get(name.casefold()),
            ):
                if found:
                    return next(iter(found)) if len(found) == 1 else None
            return name if name in self._columns else None
        if name in self._columns:
            return name
        laundered = stored_column_names([name])[0]
        if laundered in self._columns:
            return laundered
        folded = self._folded.get(name.casefold(), set())
        return next(iter(folded)) if len(folded) == 1 else None

    def __call__(self, name: str) -> str:
        """The stored column for *name*, else *name* itself, reported as a loss."""
        stored = self.stored(name)
        if stored is not None:
            return stored
        if self._loss is not None and name not in self._reported:
            self._reported.add(name)
            self._loss.add(
                self._path, "field_unmatched", f"{name} is not a column of the dataset"
            )
        return name

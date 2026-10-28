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
        self._columns: set[str] = set()
        self._by_source: dict[str, set[str]] = {}
        self._by_source_folded: dict[str, set[str]] = {}
        self._folded: dict[str, set[str]] = {}
        for c in columns or ():
            if not isinstance(c, Mapping) or not isinstance(c.get("name"), str):
                continue
            name, source = c["name"], c.get("source_name")
            self._columns.add(name)
            if isinstance(source, str):
                self._by_source.setdefault(source, set()).add(name)
                self._by_source_folded.setdefault(source.casefold(), set()).add(name)
            else:
                self._folded.setdefault(name.casefold(), set()).add(name)
        self._sourced = bool(self._by_source)
        self._path = path
        self._loss = loss
        self._reported: set[str] = set()

    def stored(self, name: str) -> str | None:
        """The column *name* is stored as: the column whose source field it is
        when columns record source names (an ambiguous match is None), else
        the same name, the name ingest gives the field when no column records
        a source name, or the one column without a source name equal to it
        ignoring case."""
        if not self._columns:
            return name
        if self._sourced:
            for found in (
                self._by_source.get(name),
                self._by_source_folded.get(name.casefold()),
            ):
                if found:
                    return next(iter(found)) if len(found) == 1 else None
        if name in self._columns:
            return name
        if not self._sourced:
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

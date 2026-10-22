"""Loss report for an ArcGIS web map translation.

Items carry a stable ``kind`` code so a UI can localize them; ``detail`` is
free text. Portal-supplied strings (titles, field names) reach the text
rendering, so every item is flattened to one clipped line.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

NOTES_MAX_CHARS = 50_000
MAX_LOSS_ITEMS = 1000
_NOTES_HEADER = "ArcGIS migration notes"
_ITEM_MAX_CHARS = 400
# C0/C1 controls, line and paragraph separators, and bidi overrides.
_CONTROL_CHARS = re.compile(
    "[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029\\u202a-\\u202e\\u2066-\\u2069]+"
)


def _one_line(text: str, limit: int) -> str:
    flat = _CONTROL_CHARS.sub(" ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class LossItem:
    path: str
    kind: str
    detail: str = ""


@dataclass
class LossReport:
    """Loss items, capped at ``MAX_LOSS_ITEMS``; the summary still counts every loss."""

    items: list[LossItem] = field(default_factory=list)
    overflow: Counter = field(default_factory=Counter)

    def add(self, path: str, kind: str, detail: str = "") -> None:
        if len(self.items) >= MAX_LOSS_ITEMS:
            self.overflow[kind] += 1
            return
        self.items.append(LossItem(_one_line(path, 255), kind, _one_line(detail, 255)))

    def merge(self, other: LossReport) -> None:
        for item in other.items:
            self.add(item.path, item.kind, item.detail)
        self.overflow.update(other.overflow)

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(item.kind for item in self.items)
        counts.update(self.overflow)
        return dict(counts)

    @property
    def dropped(self) -> int:
        return sum(self.overflow.values())

    def _all_items(self) -> list[LossItem]:
        if not self.dropped:
            return self.items
        note = LossItem("", "loss_truncated", f"{self.dropped} more entries")
        return [*self.items, note]

    def as_dict(self) -> dict:
        summary = self.summary
        if self.dropped:
            summary["loss_truncated"] = 1
        return {
            "items": [
                {"path": i.path, "kind": i.kind, "detail": i.detail}
                for i in self._all_items()
            ],
            "summary": summary,
        }

    def render_text(self, date: str, limit: int = NOTES_MAX_CHARS) -> str:
        """Plain text for the map notes, cut at the last whole line that fits."""
        header = f"{_NOTES_HEADER} ({date})"
        lines = [
            _one_line(
                f"- {i.path}: {i.kind}" + (f" ({i.detail})" if i.detail else ""),
                _ITEM_MAX_CHARS,
            )
            for i in self._all_items()
        ]
        full = "\n".join([header, *lines])
        if len(full) <= limit:
            return full

        kept: list[str] = [header]
        used = len(header)
        for index, line in enumerate(lines):
            remaining = len(lines) - index
            pointer = f"... {remaining} more entries in the CLI report"
            # Reserve room for the pointer line that would follow this entry.
            if used + 1 + len(line) + 1 + len(pointer) > limit:
                break
            kept.append(line)
            used += 1 + len(line)
        remaining = len(lines) - (len(kept) - 1)
        kept.append(f"... {remaining} more entries in the CLI report")
        return "\n".join(kept)

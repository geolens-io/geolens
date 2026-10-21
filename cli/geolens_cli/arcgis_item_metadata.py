# SPDX-License-Identifier: Apache-2.0
"""Item metadata `geolens arcgis migrate` writes onto the datasets of an item.

Hand-maintained. ``item_metadata`` maps an inventory row and its plan target
to GeoLens fields; ``apply_item_metadata`` writes them through
``PATCH /datasets/{id}`` and the record's keyword sub-resource. ArcGIS
descriptions and license text are HTML; they are stored as plain text.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

from .arcgis_migrate_session import GeoLensError, ItemFailed, MigrationContext
from .arcgis_migrate_state import ItemState

MAX_SUMMARY = 5000
MAX_ATTRIBUTION = 5000
MAX_LICENSE = 500
MAX_ORGANIZATION = 1000
MAX_KEYWORD = 500
_NO_ANGLE_BRACKETS = str.maketrans("<>", "()")
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    """*value* without markup: block elements become line breaks, runs of
    spaces collapse, and entities are decoded."""
    if not value:
        return ""
    parser = _Text()
    parser.feed(value)
    parser.close()
    text = "".join(parser.parts)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def item_metadata(
    row: Mapping[str, Any], target: Mapping[str, Any], portal: Mapping[str, Any] | None
) -> dict[str, Any]:
    """GeoLens fields for one item: ``summary`` from the snippet and the
    description, ``attribution``, ``license``, ``source_organization`` and
    the plan target's tags as ``keywords``. Empty fields are left out."""
    snippet = html_to_text(row.get("snippet"))
    description = html_to_text(row.get("description"))
    summary = "\n\n".join(p for p in (snippet, description) if p)
    fields: dict[str, Any] = {
        "summary": summary[:MAX_SUMMARY],
        # GeoLens refuses angle brackets in an attribution, which reaches an
        # HTML render context; a decoded "<contact@example.org>" would 422.
        "attribution": html_to_text(row.get("access_information")).translate(
            _NO_ANGLE_BRACKETS
        )[:MAX_ATTRIBUTION],
        "license": html_to_text(row.get("license_info"))[:MAX_LICENSE],
        "source_organization": str((portal or {}).get("name") or "")[:MAX_ORGANIZATION],
    }
    fields = {name: value for name, value in fields.items() if value}
    keywords = [t.strip()[:MAX_KEYWORD] for t in target.get("tags") or [] if t.strip()]
    fields["keywords"] = list(dict.fromkeys(keywords))
    return fields


def summary_hash(summary: str) -> str:
    return hashlib.sha256(summary.encode()).hexdigest()


def apply_item_metadata(
    ctx: MigrationContext, item: Mapping[str, Any], entry: ItemState
) -> None:
    """Write the item's metadata onto each of its datasets, as the operator.

    A summary someone edited in GeoLens since the last run is kept: it is
    replaced only when it is empty or is the one this command wrote
    (``entry.metadata_hash``).
    """
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get
    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch,
    )
    from geolens.models.dataset_meta import DatasetMeta

    row = ctx.inventory.get(item["id"])
    if row is None or not entry.dataset_ids:
        return
    fields = item_metadata(row, item["target"], ctx.portal_info)
    keywords = fields.pop("keywords")
    summary = fields.get("summary")
    record_ids: list[str] = []
    try:
        for dataset_id in entry.dataset_ids:
            meta = dict(fields)
            if summary is not None:
                current = ctx.geolens.call(
                    get.sync_detailed, dataset_id=UUID(dataset_id)
                )
                existing = current.summary if isinstance(current.summary, str) else ""
                if (
                    existing
                    and existing != summary
                    and summary_hash(existing) != entry.metadata_hash
                ):
                    del meta["summary"]
            dataset = ctx.geolens.call(
                patch.sync_detailed,
                dataset_id=UUID(dataset_id),
                body=DatasetMeta.from_dict(meta),
            )
            record_ids.append(str(dataset.record_id))
            _add_keywords(ctx, dataset.record_id, keywords)
    except GeoLensError as exc:
        raise ItemFailed(f"writing the item metadata failed, {exc}") from None
    entry.record_ids = record_ids
    if summary is not None:
        entry.metadata_hash = summary_hash(summary)
    ctx.save()


def _add_keywords(ctx: MigrationContext, record_id: Any, keywords: list[str]) -> None:
    from geolens.api.records import (
        create_keyword_endpoint_records_record_id_keywords_post as create,
    )
    from geolens.models.keyword_create import KeywordCreate

    for keyword in keywords:
        try:
            ctx.geolens.call(
                create.sync_detailed,
                record_id=UUID(str(record_id)),
                body=KeywordCreate(keyword=keyword),
                expected=201,
            )
        except GeoLensError as exc:
            if exc.status != 409:
                raise

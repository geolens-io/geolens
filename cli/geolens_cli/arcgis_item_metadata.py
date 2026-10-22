# SPDX-License-Identifier: Apache-2.0
"""Item metadata `geolens arcgis migrate` writes onto the datasets of an item.

Hand-maintained. ``item_metadata`` maps an inventory row and its plan target
to GeoLens fields; ``apply_item_metadata`` writes them through
``PATCH /datasets/{id}`` and the record's keyword sub-resource. ArcGIS
descriptions and license text are HTML; they are stored as plain text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

from .arcgis_migrate_session import GeoLensError, ItemFailed, MigrationContext
from .arcgis_migrate_state import ItemState

MAX_SUMMARY = 5000
MAX_ATTRIBUTION = 5000
MAX_LICENSE = 1000
MAX_ORGANIZATION = 1000
MAX_KEYWORD = 500
_NO_ANGLE_BRACKETS = str.maketrans("<>", "()")
# Text that merely looks like a tag: "<https://...>" or "<gis@example.org>".
# Any other well-formed tag is markup whatever its name characters, such as
# Word's "<o:p>" or a custom "<x-panel>".
_LITERAL_TAG = re.compile(r"</?(?:[a-z][a-z0-9+.-]*:/|[^\s>/]*@)", re.IGNORECASE)
# The HTML rendering section's block-level elements (display: block or a
# table or list display), the places a line break belongs.
_BLOCK_TAGS = frozenset(
    "address article aside blockquote body br caption center col colgroup dd "
    "details dialog dir div dl dt fieldset figcaption figure footer form h1 h2 "
    "h3 h4 h5 h6 head header hgroup hr html legend li listing main menu nav ol "
    "optgroup option p pre search section summary table tbody tfoot "
    "thead tr ul xmp".split()
)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        # Open links: (destination, index in parts where its label starts).
        self._links: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        raw = self.get_starttag_text() or ""
        if _LITERAL_TAG.match(raw):
            self.handle_data(raw)
        elif tag in ("script", "style"):
            self._skip += 1
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.handle_data(f" {alt} ")
        elif tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            self._links.append((href, len(self.parts)))
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        # "<br/>" is one element; a literal "<https://example.org/>" is one
        # piece of text, so it mustn't also get a closing tag.
        self.handle_starttag(tag, attrs)
        if not _LITERAL_TAG.match(self.get_starttag_text() or ""):
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if "@" in tag or tag.endswith(":"):
            self.handle_data(f"</{tag}>")
        elif tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._links:
            self._close_link()
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def _close_link(self) -> None:
        """Keep a link's destination as text beside its label; it is never
        fetched."""
        href, start = self._links.pop()
        if self._skip or not href or href.startswith("#"):
            return
        if href.lower().startswith("javascript:"):
            return
        label = " ".join("".join(self.parts[start:]).split())
        shown = href.removeprefix("mailto:")
        if not label:
            self.parts.append(href)
        elif label not in (href, shown):
            self.parts.append(f" ({href})")

    def finish(self) -> None:
        while self._links:
            self._close_link()


def html_to_text(value: str | None) -> str:
    """*value* without markup: block elements become line breaks, runs of
    spaces collapse, and entities are decoded."""
    if not value:
        return ""
    parser = _Text()
    parser.feed(value)
    parser.close()
    parser.finish()
    # NFC, as GeoLens stores it, so a summary compares and hashes the same.
    text = unicodedata.normalize("NFC", "".join(parser.parts))
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
        "source_organization": unicodedata.normalize(
            "NFC", str((portal or {}).get("name") or "")
        )[:MAX_ORGANIZATION],
    }
    fields = {name: value for name, value in fields.items() if value}
    keywords = [
        unicodedata.normalize("NFC", t.strip())[:MAX_KEYWORD]
        for t in target.get("tags") or []
        if t.strip()
    ]
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
        # Saved once every summary is written and before the keywords, which
        # can fail: a rerun must still tell its own summary from an edit. Not
        # per dataset, since the datasets not yet written still hold the old one.
        entry.record_ids = record_ids
        if summary is not None:
            entry.metadata_hash = summary_hash(summary)
        ctx.save()
        for record_id in record_ids:
            _add_keywords(ctx, record_id, keywords)
    except GeoLensError as exc:
        raise ItemFailed(f"writing the item metadata failed, {exc}") from None


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

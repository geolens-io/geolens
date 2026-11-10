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
from collections.abc import Container, Mapping
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
        shown = re.sub(r"^mailto:", "", href, flags=re.IGNORECASE)
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
        unicodedata.normalize("NFC", t.strip().lower())[:MAX_KEYWORD]
        for t in target.get("tags") or []
        if t.strip()
    ]
    fields["keywords"] = list(dict.fromkeys(keywords))
    return fields


def summary_hash(summary: str) -> str:
    return hashlib.sha256(summary.encode()).hexdigest()


_DATASET_ATTRS = {"license": "license_"}


def _current(dataset: Any, name: str) -> str:
    value = getattr(dataset, _DATASET_ATTRS.get(name, name), None)
    return value if isinstance(value, str) else ""


def _decide(
    name: str, existing: str, value: str, base: Mapping[str, Any] | None, old_hash: Any
) -> tuple[str, bool]:
    """What to do with a field now holding *existing* when the source says
    *value*: ``("write" | "keep" | "same", claim)``, where *claim* records
    *value* in the baseline.

    The baseline holds a field only if this command wrote that value, so
    equality with what GeoLens holds claims nothing. The exception is a dataset
    with no baseline at all, from a state file that predates it or a dataset
    seen for the first time: there an equal value is taken as ours, except a
    summary the file's ``metadata_hash`` doesn't vouch for.
    """
    if base is None:
        ours = name != "summary" or summary_hash(existing) == old_hash
        if existing == value:
            return "same", ours
        if name != "summary" or not existing or ours:
            return "write", True
        return "keep", False
    if existing == value:
        return "same", False
    if existing == base.get(name, ""):
        return "write", True
    return "keep", False


def apply_item_metadata(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    datasets: Container[str] | None = None,
) -> None:
    """Write the item's metadata onto each of its datasets, or only those in
    *datasets*, as the operator.

    A field someone edited in GeoLens since the last run is kept and listed in
    the item's notes: a field is written only while it still holds what this
    command wrote (``entry.metadata_baseline``), or is empty.
    """
    from geolens.api.datasets import get_single_dataset_datasets_dataset_id_get as get
    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch,
    )
    from geolens.models.dataset_meta import DatasetMeta

    row = ctx.inventory.get(item["id"])
    ids = [d for d in entry.dataset_ids if datasets is None or d in datasets]
    if row is None or not ids:
        return
    fields = item_metadata(row, item["target"], ctx.portal_info)
    keywords = fields.pop("keywords")
    record_ids: list[str] = []
    try:
        for dataset_id in ids:
            current = ctx.geolens.call(get.sync_detailed, dataset_id=UUID(dataset_id))
            base = entry.metadata_baseline.get(dataset_id)
            meta: dict[str, Any] = {}
            baseline = dict(base or {})
            # A field this command wrote that the portal has since emptied is
            # emptied too, by the same rule as any other change.
            cleared = {
                name: ""
                for name, written in (base or {}).items()
                if name != "keywords" and written and name not in fields
            }
            for name, value in {**fields, **cleared}.items():
                action, claim = _decide(
                    name, _current(current, name), value, base, entry.metadata_hash
                )
                if action == "write":
                    meta[name] = value or None
                elif action == "keep":
                    entry.notes.append(
                        f"kept the {name.replace('_', ' ')} edited in GeoLens on "
                        f"dataset {dataset_id}"
                    )
                if claim:
                    baseline[name] = value
            baseline.setdefault("keywords", [])
            if meta:
                meta["expected_updated_at"] = current.updated_at.isoformat()
                ctx.geolens.write(
                    patch.sync_detailed,
                    during="its metadata was written",
                    dataset_id=UUID(dataset_id),
                    body=DatasetMeta.from_dict(meta),
                )
            record_ids.append(str(current.record_id))
            entry.metadata_baseline[dataset_id] = baseline
        # Saved once every dataset is written and before the keywords, which
        # can fail: a rerun must still tell its own fields from an edit.
        if len(ids) == len(entry.dataset_ids):
            entry.record_ids = record_ids
        ctx.save()
        for dataset_id, record_id in zip(ids, record_ids, strict=True):
            kept = _add_keywords(
                ctx,
                record_id,
                keywords,
                entry.metadata_baseline[dataset_id]["keywords"],
            )
            entry.notes.extend(
                f"kept the removal of keyword {word!r} on dataset {dataset_id}"
                for word in kept
            )
    except GeoLensError as exc:
        raise ItemFailed(f"writing the item metadata failed, {exc}") from None
    ctx.save()


def _plan_keywords(
    wanted: list[str], written: list[str], present: set[str]
) -> tuple[list[str], list[str]]:
    """The keywords to create, and those this command created that someone
    has since removed, which stay removed."""
    kept = [word for word in wanted if word in written and word not in present]
    add = [word for word in wanted if word not in present and word not in kept]
    return add, kept


def _add_keywords(
    ctx: MigrationContext, record_id: Any, keywords: list[str], written: list[str]
) -> list[str]:
    """Create the keywords the record lacks and append each to *written* as it
    succeeds, so a later failure can't forget it; returns the removed ones."""
    from geolens.api.records import (
        create_keyword_endpoint_records_record_id_keywords_post as create,
    )
    from geolens.api.records import (
        list_keywords_endpoint_records_record_id_keywords_get as listing,
    )
    from geolens.models.keyword_create import KeywordCreate

    listed = ctx.geolens.call(
        listing.sync_detailed, record_id=UUID(str(record_id)), limit=500
    )
    # Only a plain theme keyword conflicts with the one created below; the
    # same text under another type or vocabulary is a different keyword. An
    # inherited row is a stored row too, so it conflicts.
    present = {
        k.keyword
        for k in listed.keywords
        if k.keyword_type == "theme" and not k.vocabulary_uri
    }
    add, kept = _plan_keywords(keywords, written, present)
    for keyword in add:
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
        else:
            written.append(keyword)
    return kept

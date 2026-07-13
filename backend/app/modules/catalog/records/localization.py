"""Language negotiation for catalog record title/summary text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class _Translation(Protocol):
    language: str
    title: str
    summary: str | None


class _Record(Protocol):
    language: str | None
    title: str
    summary: str | None
    translations: Iterable[_Translation]


@dataclass(frozen=True)
class LocalizedRecordText:
    language: str
    title: str
    summary: str | None


def _normalize_language_tag(
    language: str | None, fallback: str | None = None
) -> str | None:
    if language is None:
        return fallback
    parts = [part for part in language.strip().replace("_", "-").split("-") if part]
    if not parts:
        return fallback
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def select_localized_record_text(
    record: _Record,
    preferred_languages: Iterable[str] | None = None,
) -> LocalizedRecordText:
    """Select the closest stored representation for ordered language wishes.

    Exact BCP 47 matches win, followed by a same-base-language representation.
    When no requested representation exists, the record's primary text is the
    stable fallback.  The returned language is always the language of the text
    actually selected, so response headers cannot echo an unsupported request.
    """
    primary_language = _normalize_language_tag(record.language, fallback="en") or "en"
    primary = LocalizedRecordText(primary_language, record.title, record.summary)

    requested_languages = tuple(preferred_languages or ())
    if not requested_languages:
        # Most internal serializers do not negotiate a representation. Avoid
        # touching the lazy="raise" relationship in that path; callers that do
        # negotiate must still eager-load translations and fail fast if they do
        # not, preserving the catalog query-discipline guard.
        return primary

    variants: list[LocalizedRecordText] = [primary]
    for translation in getattr(record, "translations", ()) or ():
        language = _normalize_language_tag(translation.language)
        if language is None:
            continue
        variants.append(
            LocalizedRecordText(language, translation.title, translation.summary)
        )

    # Preserve the primary representation when a redundant translation row uses
    # the same language tag; it remains the catalog's source of truth.
    exact: dict[str, LocalizedRecordText] = {}
    for variant in variants:
        exact.setdefault(variant.language.lower(), variant)

    for requested in requested_languages:
        normalized = _normalize_language_tag(requested)
        if normalized is None:
            continue

        # RFC 4647 lookup: progressively truncate a requested tag before the
        # broader same-base fallback (zh-Hant-TW -> zh-Hant -> zh).
        lookup_parts = normalized.split("-")
        while lookup_parts:
            match = exact.get("-".join(lookup_parts).lower())
            if match is not None:
                return match
            lookup_parts.pop()

        base = normalized.split("-", 1)[0].lower()
        base_candidates = [
            variant
            for variant in variants
            if variant.language.split("-", 1)[0].lower() == base
        ]
        if base_candidates:
            # Prefer an unqualified base tag, then the primary representation,
            # then lexical order for deterministic regional fallback.
            base_candidates.sort(
                key=lambda variant: (
                    variant.language.lower() != base,
                    variant is not primary,
                    variant.language.lower(),
                )
            )
            return base_candidates[0]

    return primary

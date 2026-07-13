"""Metadata value-shape helpers for OGC API Records serialization."""

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset


def build_themes(
    theme_category: list[str] | None,
    keywords: list | None = None,
) -> list[dict]:
    """Convert theme categories and keyword vocabularies to OGC themes."""
    themes: list[dict] = []
    if keywords:
        by_vocab: dict[str | None, list[str]] = {}
        for keyword in keywords:
            uri = getattr(keyword, "vocabulary_uri", None)
            by_vocab.setdefault(uri, []).append(keyword.keyword)
        for uri, values in by_vocab.items():
            entry: dict = {"concepts": [{"id": value} for value in values]}
            if uri:
                entry["scheme"] = uri
            themes.append(entry)
    if not themes and theme_category:
        themes.append({"concepts": [{"id": value} for value in theme_category]})
    return themes


def build_time(dataset: Dataset) -> dict:
    """Build the required OGC record time object from known metadata."""
    record = dataset.record
    start = record.temporal_start
    end = record.temporal_end
    if start is None and end is None:
        timestamp = record.created_at or record.updated_at
        if timestamp is not None:
            return {"timestamp": timestamp.isoformat().replace("+00:00", "Z")}
        return {"interval": [["..", ".."]]}
    return {
        "interval": [
            [
                start.isoformat() if start else "..",
                end.isoformat() if end else "..",
            ]
        ]
    }


def build_contacts(dataset: Dataset) -> list[dict]:
    """Build OGC contacts with the core ``name`` and ``roles`` fields."""
    contacts: list[dict] = []
    for contact in dataset.record.contacts:
        entry = {
            "name": contact.name or contact.organization or "Dataset metadata contact",
            "organization": contact.organization,
            "roles": [contact.role] if contact.role else ["pointOfContact"],
            "email": contact.email,
            "phone": contact.phone,
        }
        contacts.append(
            {key: value for key, value in entry.items() if value is not None}
        )

    if contacts:
        return contacts
    if settings.dcat_contact_email:
        return [
            {
                "name": "Catalog metadata contact",
                "roles": ["pointOfContact"],
                "email": settings.dcat_contact_email,
            }
        ]
    return [
        {
            "name": "GeoLens metadata catalog",
            "organization": "GeoLens",
            "roles": ["publisher"],
        }
    ]


def build_external_ids(dataset: Dataset) -> list[str]:
    """Return canonical identifiers assigned by an external source system."""
    if dataset.source_format == "stac" and dataset.source_filename:
        return [dataset.source_filename]
    return []

from typing import Literal, cast

ManifestPublicationIntent = Literal["draft", "internal", "published", "ready"]

MANIFEST_PUBLICATION_INTENT_VALUES: set[ManifestPublicationIntent] = {
    "draft",
    "internal",
    "published",
    "ready",
}


def check_manifest_publication_intent(value: str) -> ManifestPublicationIntent:
    if value in MANIFEST_PUBLICATION_INTENT_VALUES:
        return cast(ManifestPublicationIntent, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_PUBLICATION_INTENT_VALUES!r}"
    )

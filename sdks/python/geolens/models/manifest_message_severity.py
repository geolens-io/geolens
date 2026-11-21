from typing import Literal, cast

ManifestMessageSeverity = Literal["error", "info", "warning"]

MANIFEST_MESSAGE_SEVERITY_VALUES: set[ManifestMessageSeverity] = {
    "error",
    "info",
    "warning",
}


def check_manifest_message_severity(value: str) -> ManifestMessageSeverity:
    if value in MANIFEST_MESSAGE_SEVERITY_VALUES:
        return cast(ManifestMessageSeverity, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_MESSAGE_SEVERITY_VALUES!r}"
    )

from typing import Literal, cast

SourceHealthResponseSourceHealth = Literal["healthy", "inaccessible", "missing"]

SOURCE_HEALTH_RESPONSE_SOURCE_HEALTH_VALUES: set[SourceHealthResponseSourceHealth] = {
    "healthy",
    "inaccessible",
    "missing",
}


def check_source_health_response_source_health(
    value: str,
) -> SourceHealthResponseSourceHealth:
    if value in SOURCE_HEALTH_RESPONSE_SOURCE_HEALTH_VALUES:
        return cast(SourceHealthResponseSourceHealth, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SOURCE_HEALTH_RESPONSE_SOURCE_HEALTH_VALUES!r}"
    )

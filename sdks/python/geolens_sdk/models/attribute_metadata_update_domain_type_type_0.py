from typing import Literal, cast

AttributeMetadataUpdateDomainTypeType0 = Literal[
    "boolean",
    "categorical",
    "coded",
    "codedValue",
    "continuous",
    "date",
    "discrete",
    "geometry",
    "range",
    "temporal",
    "text",
]

ATTRIBUTE_METADATA_UPDATE_DOMAIN_TYPE_TYPE_0_VALUES: set[
    AttributeMetadataUpdateDomainTypeType0
] = {
    "boolean",
    "categorical",
    "coded",
    "codedValue",
    "continuous",
    "date",
    "discrete",
    "geometry",
    "range",
    "temporal",
    "text",
}


def check_attribute_metadata_update_domain_type_type_0(
    value: str,
) -> AttributeMetadataUpdateDomainTypeType0:
    if value in ATTRIBUTE_METADATA_UPDATE_DOMAIN_TYPE_TYPE_0_VALUES:
        return cast(AttributeMetadataUpdateDomainTypeType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ATTRIBUTE_METADATA_UPDATE_DOMAIN_TYPE_TYPE_0_VALUES!r}"
    )

from typing import Literal, cast

AttributeMetadataUpdateSemanticRoleType0 = Literal[
    "categorical",
    "category",
    "foreign_key",
    "geometry",
    "identifier",
    "label",
    "measure",
    "other",
    "temporal",
]

ATTRIBUTE_METADATA_UPDATE_SEMANTIC_ROLE_TYPE_0_VALUES: set[
    AttributeMetadataUpdateSemanticRoleType0
] = {
    "categorical",
    "category",
    "foreign_key",
    "geometry",
    "identifier",
    "label",
    "measure",
    "other",
    "temporal",
}


def check_attribute_metadata_update_semantic_role_type_0(
    value: str,
) -> AttributeMetadataUpdateSemanticRoleType0:
    if value in ATTRIBUTE_METADATA_UPDATE_SEMANTIC_ROLE_TYPE_0_VALUES:
        return cast(AttributeMetadataUpdateSemanticRoleType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ATTRIBUTE_METADATA_UPDATE_SEMANTIC_ROLE_TYPE_0_VALUES!r}"
    )

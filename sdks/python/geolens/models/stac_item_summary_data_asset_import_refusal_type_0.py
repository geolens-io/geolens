from typing import Literal, cast

StacItemSummaryDataAssetImportRefusalType0 = Literal[
    "credentials", "not_http", "too_long"
]

STAC_ITEM_SUMMARY_DATA_ASSET_IMPORT_REFUSAL_TYPE_0_VALUES: set[
    StacItemSummaryDataAssetImportRefusalType0
] = {
    "credentials",
    "not_http",
    "too_long",
}


def check_stac_item_summary_data_asset_import_refusal_type_0(
    value: str,
) -> StacItemSummaryDataAssetImportRefusalType0:
    if value in STAC_ITEM_SUMMARY_DATA_ASSET_IMPORT_REFUSAL_TYPE_0_VALUES:
        return cast(StacItemSummaryDataAssetImportRefusalType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STAC_ITEM_SUMMARY_DATA_ASSET_IMPORT_REFUSAL_TYPE_0_VALUES!r}"
    )

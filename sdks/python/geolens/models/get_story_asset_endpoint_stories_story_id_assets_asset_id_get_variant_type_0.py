from typing import Literal, cast

GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0 = Literal[
    "card", "social"
]

GET_STORY_ASSET_ENDPOINT_STORIES_STORY_ID_ASSETS_ASSET_ID_GET_VARIANT_TYPE_0_VALUES: set[
    GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0
] = {
    "card",
    "social",
}


def check_get_story_asset_endpoint_stories_story_id_assets_asset_id_get_variant_type_0(
    value: str,
) -> GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0:
    if (
        value
        in GET_STORY_ASSET_ENDPOINT_STORIES_STORY_ID_ASSETS_ASSET_ID_GET_VARIANT_TYPE_0_VALUES
    ):
        return cast(
            GetStoryAssetEndpointStoriesStoryIdAssetsAssetIdGetVariantType0, value
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GET_STORY_ASSET_ENDPOINT_STORIES_STORY_ID_ASSETS_ASSET_ID_GET_VARIANT_TYPE_0_VALUES!r}"
    )

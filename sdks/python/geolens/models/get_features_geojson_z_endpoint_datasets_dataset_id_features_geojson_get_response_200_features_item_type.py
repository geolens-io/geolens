from typing import Literal, cast

GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType = Literal[
    "Feature"
]

GET_FEATURES_GEOJSON_Z_ENDPOINT_DATASETS_DATASET_ID_FEATURES_GEOJSON_GET_RESPONSE_200_FEATURES_ITEM_TYPE_VALUES: set[
    GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType
] = {
    "Feature",
}


def check_get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_type(
    value: str,
) -> GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType:
    if (
        value
        in GET_FEATURES_GEOJSON_Z_ENDPOINT_DATASETS_DATASET_ID_FEATURES_GEOJSON_GET_RESPONSE_200_FEATURES_ITEM_TYPE_VALUES
    ):
        return cast(
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GET_FEATURES_GEOJSON_Z_ENDPOINT_DATASETS_DATASET_ID_FEATURES_GEOJSON_GET_RESPONSE_200_FEATURES_ITEM_TYPE_VALUES!r}"
    )

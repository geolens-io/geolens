from typing import Literal, cast

ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

LIST_FEATURES_DATASETS_DATASET_ID_FEATURES_GET_GEO_JSON_FEATURE_COLLECTION_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_type(
    value: str,
) -> ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryType:
    if (
        value
        in LIST_FEATURES_DATASETS_DATASET_ID_FEATURES_GET_GEO_JSON_FEATURE_COLLECTION_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_FEATURES_DATASETS_DATASET_ID_FEATURES_GET_GEO_JSON_FEATURE_COLLECTION_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

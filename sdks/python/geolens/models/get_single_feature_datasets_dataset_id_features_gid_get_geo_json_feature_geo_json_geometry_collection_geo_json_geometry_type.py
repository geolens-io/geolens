from typing import Literal, cast

GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

GET_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_GET_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type(
    value: str,
) -> GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType:
    if (
        value
        in GET_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_GET_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GET_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_GET_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

from typing import Literal, cast

ReplaceSingleFeatureDatasetsDatasetIdFeaturesGidPutGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

REPLACE_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PUT_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    ReplaceSingleFeatureDatasetsDatasetIdFeaturesGidPutGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_replace_single_feature_datasets_dataset_id_features_gid_put_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type(
    value: str,
) -> ReplaceSingleFeatureDatasetsDatasetIdFeaturesGidPutGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType:
    if (
        value
        in REPLACE_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PUT_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            ReplaceSingleFeatureDatasetsDatasetIdFeaturesGidPutGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REPLACE_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PUT_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

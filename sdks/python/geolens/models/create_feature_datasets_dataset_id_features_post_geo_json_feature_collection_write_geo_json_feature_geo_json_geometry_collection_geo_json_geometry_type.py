from typing import Literal, cast

CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_WRITE_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type(
    value: str,
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType:
    if (
        value
        in CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_WRITE_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_WRITE_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

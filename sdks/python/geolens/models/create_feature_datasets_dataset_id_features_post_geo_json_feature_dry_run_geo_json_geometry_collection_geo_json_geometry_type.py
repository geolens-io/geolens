from typing import Literal, cast

CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureDryRunGeoJSONGeometryCollectionGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureDryRunGeoJSONGeometryCollectionGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_create_feature_datasets_dataset_id_features_post_geo_json_feature_dry_run_geo_json_geometry_collection_geo_json_geometry_type(
    value: str,
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureDryRunGeoJSONGeometryCollectionGeoJSONGeometryType:
    if (
        value
        in CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureDryRunGeoJSONGeometryCollectionGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_COLLECTION_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

from typing import Literal, cast

CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRunGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_DRY_RUN_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRunGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run_geo_json_feature_dry_run_geo_json_geometry_type(
    value: str,
) -> CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRunGeoJSONGeometryType:
    if (
        value
        in CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_DRY_RUN_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRunGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_POST_GEO_JSON_FEATURE_COLLECTION_DRY_RUN_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

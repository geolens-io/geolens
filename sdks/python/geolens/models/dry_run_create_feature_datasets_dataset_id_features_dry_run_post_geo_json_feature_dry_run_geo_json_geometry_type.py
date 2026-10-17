from typing import Literal, cast

DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

DRY_RUN_CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_DRY_RUN_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry_type(
    value: str,
) -> DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryType:
    if (
        value
        in DRY_RUN_CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_DRY_RUN_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DRY_RUN_CREATE_FEATURE_DATASETS_DATASET_ID_FEATURES_DRY_RUN_POST_GEO_JSON_FEATURE_DRY_RUN_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

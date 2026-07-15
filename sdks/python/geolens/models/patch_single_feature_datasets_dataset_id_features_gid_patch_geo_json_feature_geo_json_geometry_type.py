from typing import Literal, cast

PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryType = (
    Literal[
        "LineString",
        "MultiLineString",
        "MultiPoint",
        "MultiPolygon",
        "Point",
        "Polygon",
    ]
)

PATCH_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PATCH_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_type(
    value: str,
) -> (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryType
):
    if (
        value
        in PATCH_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PATCH_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {PATCH_SINGLE_FEATURE_DATASETS_DATASET_ID_FEATURES_GID_PATCH_GEO_JSON_FEATURE_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

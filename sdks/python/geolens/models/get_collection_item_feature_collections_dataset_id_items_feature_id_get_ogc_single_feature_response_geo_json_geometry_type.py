from typing import Literal, cast

GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponseGeoJSONGeometryType = Literal[
    "LineString", "MultiLineString", "MultiPoint", "MultiPolygon", "Point", "Polygon"
]

GET_COLLECTION_ITEM_FEATURE_COLLECTIONS_DATASET_ID_ITEMS_FEATURE_ID_GET_OGC_SINGLE_FEATURE_RESPONSE_GEO_JSON_GEOMETRY_TYPE_VALUES: set[
    GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponseGeoJSONGeometryType
] = {
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
}


def check_get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response_geo_json_geometry_type(
    value: str,
) -> GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponseGeoJSONGeometryType:
    if (
        value
        in GET_COLLECTION_ITEM_FEATURE_COLLECTIONS_DATASET_ID_ITEMS_FEATURE_ID_GET_OGC_SINGLE_FEATURE_RESPONSE_GEO_JSON_GEOMETRY_TYPE_VALUES
    ):
        return cast(
            GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponseGeoJSONGeometryType,
            value,
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GET_COLLECTION_ITEM_FEATURE_COLLECTIONS_DATASET_ID_ITEMS_FEATURE_ID_GET_OGC_SINGLE_FEATURE_RESPONSE_GEO_JSON_GEOMETRY_TYPE_VALUES!r}"
    )

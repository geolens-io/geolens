from typing import Literal, cast

CollectionItemsCollectionsDatasetsItemsGetSpatialPredicate = Literal[
    "intersects", "within"
]

COLLECTION_ITEMS_COLLECTIONS_DATASETS_ITEMS_GET_SPATIAL_PREDICATE_VALUES: set[
    CollectionItemsCollectionsDatasetsItemsGetSpatialPredicate
] = {
    "intersects",
    "within",
}


def check_collection_items_collections_datasets_items_get_spatial_predicate(
    value: str,
) -> CollectionItemsCollectionsDatasetsItemsGetSpatialPredicate:
    if (
        value
        in COLLECTION_ITEMS_COLLECTIONS_DATASETS_ITEMS_GET_SPATIAL_PREDICATE_VALUES
    ):
        return cast(CollectionItemsCollectionsDatasetsItemsGetSpatialPredicate, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {COLLECTION_ITEMS_COLLECTIONS_DATASETS_ITEMS_GET_SPATIAL_PREDICATE_VALUES!r}"
    )

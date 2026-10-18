from typing import Literal, cast

GetDatasetRowsEndpointDatasetsDatasetIdRowsGetOrder = Literal["asc", "desc"]

GET_DATASET_ROWS_ENDPOINT_DATASETS_DATASET_ID_ROWS_GET_ORDER_VALUES: set[
    GetDatasetRowsEndpointDatasetsDatasetIdRowsGetOrder
] = {
    "asc",
    "desc",
}


def check_get_dataset_rows_endpoint_datasets_dataset_id_rows_get_order(
    value: str,
) -> GetDatasetRowsEndpointDatasetsDatasetIdRowsGetOrder:
    if value in GET_DATASET_ROWS_ENDPOINT_DATASETS_DATASET_ID_ROWS_GET_ORDER_VALUES:
        return cast(GetDatasetRowsEndpointDatasetsDatasetIdRowsGetOrder, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GET_DATASET_ROWS_ENDPOINT_DATASETS_DATASET_ID_ROWS_GET_ORDER_VALUES!r}"
    )

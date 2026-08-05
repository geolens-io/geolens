from typing import Literal, cast

ListShareTokensEndpointAdminShareTokensGetOrder = Literal["asc", "desc"]

LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_ORDER_VALUES: set[
    ListShareTokensEndpointAdminShareTokensGetOrder
] = {
    "asc",
    "desc",
}


def check_list_share_tokens_endpoint_admin_share_tokens_get_order(
    value: str,
) -> ListShareTokensEndpointAdminShareTokensGetOrder:
    if value in LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_ORDER_VALUES:
        return cast(ListShareTokensEndpointAdminShareTokensGetOrder, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_ORDER_VALUES!r}"
    )

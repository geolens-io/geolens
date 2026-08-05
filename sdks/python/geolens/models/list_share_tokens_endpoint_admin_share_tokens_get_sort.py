from typing import Literal, cast

ListShareTokensEndpointAdminShareTokensGetSort = Literal[
    "created_at", "creator", "embed_token_count", "expires_at", "map_name"
]

LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_SORT_VALUES: set[
    ListShareTokensEndpointAdminShareTokensGetSort
] = {
    "created_at",
    "creator",
    "embed_token_count",
    "expires_at",
    "map_name",
}


def check_list_share_tokens_endpoint_admin_share_tokens_get_sort(
    value: str,
) -> ListShareTokensEndpointAdminShareTokensGetSort:
    if value in LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_SORT_VALUES:
        return cast(ListShareTokensEndpointAdminShareTokensGetSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_SHARE_TOKENS_ENDPOINT_ADMIN_SHARE_TOKENS_GET_SORT_VALUES!r}"
    )

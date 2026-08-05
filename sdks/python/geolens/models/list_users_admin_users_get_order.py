from typing import Literal, cast

ListUsersAdminUsersGetOrder = Literal["asc", "desc"]

LIST_USERS_ADMIN_USERS_GET_ORDER_VALUES: set[ListUsersAdminUsersGetOrder] = {
    "asc",
    "desc",
}


def check_list_users_admin_users_get_order(value: str) -> ListUsersAdminUsersGetOrder:
    if value in LIST_USERS_ADMIN_USERS_GET_ORDER_VALUES:
        return cast(ListUsersAdminUsersGetOrder, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_USERS_ADMIN_USERS_GET_ORDER_VALUES!r}"
    )

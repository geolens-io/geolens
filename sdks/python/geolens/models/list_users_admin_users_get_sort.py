from typing import Literal, cast

ListUsersAdminUsersGetSort = Literal[
    "created_at", "email", "last_login_at", "status", "username"
]

LIST_USERS_ADMIN_USERS_GET_SORT_VALUES: set[ListUsersAdminUsersGetSort] = {
    "created_at",
    "email",
    "last_login_at",
    "status",
    "username",
}


def check_list_users_admin_users_get_sort(value: str) -> ListUsersAdminUsersGetSort:
    if value in LIST_USERS_ADMIN_USERS_GET_SORT_VALUES:
        return cast(ListUsersAdminUsersGetSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_USERS_ADMIN_USERS_GET_SORT_VALUES!r}"
    )

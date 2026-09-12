from typing import Literal, cast

ListUsersAdminUsersGetRoleType0 = Literal["admin", "editor", "viewer"]

LIST_USERS_ADMIN_USERS_GET_ROLE_TYPE_0_VALUES: set[ListUsersAdminUsersGetRoleType0] = {
    "admin",
    "editor",
    "viewer",
}


def check_list_users_admin_users_get_role_type_0(
    value: str,
) -> ListUsersAdminUsersGetRoleType0:
    if value in LIST_USERS_ADMIN_USERS_GET_ROLE_TYPE_0_VALUES:
        return cast(ListUsersAdminUsersGetRoleType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_USERS_ADMIN_USERS_GET_ROLE_TYPE_0_VALUES!r}"
    )

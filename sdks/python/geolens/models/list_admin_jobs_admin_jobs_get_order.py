from typing import Literal, cast

ListAdminJobsAdminJobsGetOrder = Literal["asc", "desc"]

LIST_ADMIN_JOBS_ADMIN_JOBS_GET_ORDER_VALUES: set[ListAdminJobsAdminJobsGetOrder] = {
    "asc",
    "desc",
}


def check_list_admin_jobs_admin_jobs_get_order(
    value: str,
) -> ListAdminJobsAdminJobsGetOrder:
    if value in LIST_ADMIN_JOBS_ADMIN_JOBS_GET_ORDER_VALUES:
        return cast(ListAdminJobsAdminJobsGetOrder, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_ADMIN_JOBS_ADMIN_JOBS_GET_ORDER_VALUES!r}"
    )

from typing import Literal, cast

ListAdminJobsAdminJobsGetSort = Literal[
    "created_at", "duration", "source_filename", "status", "username"
]

LIST_ADMIN_JOBS_ADMIN_JOBS_GET_SORT_VALUES: set[ListAdminJobsAdminJobsGetSort] = {
    "created_at",
    "duration",
    "source_filename",
    "status",
    "username",
}


def check_list_admin_jobs_admin_jobs_get_sort(
    value: str,
) -> ListAdminJobsAdminJobsGetSort:
    if value in LIST_ADMIN_JOBS_ADMIN_JOBS_GET_SORT_VALUES:
        return cast(ListAdminJobsAdminJobsGetSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_ADMIN_JOBS_ADMIN_JOBS_GET_SORT_VALUES!r}"
    )

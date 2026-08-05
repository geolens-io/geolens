from typing import Literal, cast

ListAuditLogsAdminAuditLogsGetSort = Literal[
    "action", "created_at", "ip_address", "resource_type", "username"
]

LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_SORT_VALUES: set[
    ListAuditLogsAdminAuditLogsGetSort
] = {
    "action",
    "created_at",
    "ip_address",
    "resource_type",
    "username",
}


def check_list_audit_logs_admin_audit_logs_get_sort(
    value: str,
) -> ListAuditLogsAdminAuditLogsGetSort:
    if value in LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_SORT_VALUES:
        return cast(ListAuditLogsAdminAuditLogsGetSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_SORT_VALUES!r}"
    )

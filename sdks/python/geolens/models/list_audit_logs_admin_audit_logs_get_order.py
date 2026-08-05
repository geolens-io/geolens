from typing import Literal, cast

ListAuditLogsAdminAuditLogsGetOrder = Literal["asc", "desc"]

LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_ORDER_VALUES: set[
    ListAuditLogsAdminAuditLogsGetOrder
] = {
    "asc",
    "desc",
}


def check_list_audit_logs_admin_audit_logs_get_order(
    value: str,
) -> ListAuditLogsAdminAuditLogsGetOrder:
    if value in LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_ORDER_VALUES:
        return cast(ListAuditLogsAdminAuditLogsGetOrder, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_AUDIT_LOGS_ADMIN_AUDIT_LOGS_GET_ORDER_VALUES!r}"
    )

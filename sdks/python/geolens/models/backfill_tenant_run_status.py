from typing import Literal, cast

BackfillTenantRunStatus = Literal["already_running", "not_queued", "pending"]

BACKFILL_TENANT_RUN_STATUS_VALUES: set[BackfillTenantRunStatus] = {
    "already_running",
    "not_queued",
    "pending",
}


def check_backfill_tenant_run_status(value: str) -> BackfillTenantRunStatus:
    if value in BACKFILL_TENANT_RUN_STATUS_VALUES:
        return cast(BackfillTenantRunStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BACKFILL_TENANT_RUN_STATUS_VALUES!r}"
    )

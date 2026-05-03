from typing import Literal, cast

DryRunConfigurationConfigOpsDryRunPostMode = Literal["merge", "overwrite"]

DRY_RUN_CONFIGURATION_CONFIG_OPS_DRY_RUN_POST_MODE_VALUES: set[
    DryRunConfigurationConfigOpsDryRunPostMode
] = {
    "merge",
    "overwrite",
}


def check_dry_run_configuration_config_ops_dry_run_post_mode(
    value: str,
) -> DryRunConfigurationConfigOpsDryRunPostMode:
    if value in DRY_RUN_CONFIGURATION_CONFIG_OPS_DRY_RUN_POST_MODE_VALUES:
        return cast(DryRunConfigurationConfigOpsDryRunPostMode, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DRY_RUN_CONFIGURATION_CONFIG_OPS_DRY_RUN_POST_MODE_VALUES!r}"
    )

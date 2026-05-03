from typing import Literal, cast

ImportConfigurationConfigOpsImportPostMode = Literal["merge", "overwrite"]

IMPORT_CONFIGURATION_CONFIG_OPS_IMPORT_POST_MODE_VALUES: set[
    ImportConfigurationConfigOpsImportPostMode
] = {
    "merge",
    "overwrite",
}


def check_import_configuration_config_ops_import_post_mode(
    value: str,
) -> ImportConfigurationConfigOpsImportPostMode:
    if value in IMPORT_CONFIGURATION_CONFIG_OPS_IMPORT_POST_MODE_VALUES:
        return cast(ImportConfigurationConfigOpsImportPostMode, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {IMPORT_CONFIGURATION_CONFIG_OPS_IMPORT_POST_MODE_VALUES!r}"
    )

from typing import Literal, cast

OAuthProviderUpdateProviderTypeType0 = Literal["google", "microsoft", "oidc", "saml"]

O_AUTH_PROVIDER_UPDATE_PROVIDER_TYPE_TYPE_0_VALUES: set[
    OAuthProviderUpdateProviderTypeType0
] = {
    "google",
    "microsoft",
    "oidc",
    "saml",
}


def check_o_auth_provider_update_provider_type_type_0(
    value: str,
) -> OAuthProviderUpdateProviderTypeType0:
    if value in O_AUTH_PROVIDER_UPDATE_PROVIDER_TYPE_TYPE_0_VALUES:
        return cast(OAuthProviderUpdateProviderTypeType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {O_AUTH_PROVIDER_UPDATE_PROVIDER_TYPE_TYPE_0_VALUES!r}"
    )

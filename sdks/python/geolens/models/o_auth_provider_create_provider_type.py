from typing import Literal, cast

OAuthProviderCreateProviderType = Literal["google", "microsoft", "oidc", "saml"]

O_AUTH_PROVIDER_CREATE_PROVIDER_TYPE_VALUES: set[OAuthProviderCreateProviderType] = {
    "google",
    "microsoft",
    "oidc",
    "saml",
}


def check_o_auth_provider_create_provider_type(
    value: str,
) -> OAuthProviderCreateProviderType:
    if value in O_AUTH_PROVIDER_CREATE_PROVIDER_TYPE_VALUES:
        return cast(OAuthProviderCreateProviderType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {O_AUTH_PROVIDER_CREATE_PROVIDER_TYPE_VALUES!r}"
    )

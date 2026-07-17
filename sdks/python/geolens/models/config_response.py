from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ConfigResponse")


@_attrs_define
class ConfigResponse:
    """
    Attributes:
        registration_enabled (bool): Whether self-service registration is open
        allow_signup (bool | Unset): Whether self-serve registration is open. Alias for registration_enabled; login UI
            uses this to show/hide the signup link. Default: False.
        auth_methods (list[str] | Unset): Auth methods contributed by the active AuthExtension. Empty by default;
            compatible deployments may add methods such as ['saml']. Login UI can render conditional sign-in options without
            needing admin OAuthProvider access.
        banner_color (str | Unset): Theme token for the site banner color: warning | info | success | destructive.
            Default: 'warning'.
        banner_enabled (bool | Unset): When true and banner_text is non-empty, the site-wide announcement banner is
            shown. Default false. Default: False.
        banner_text (str | Unset): Admin-configured site-wide announcement banner text. Empty string means no banner is
            shown. Default: ''.
        demo_mode (bool | Unset): When true, logged-in users see a persistent demo-account banner. Default false — self-
            hosters see no banner. Default: False.
        email_verification_required (bool | Unset): When true, new self-registered users must verify their email before
            logging in. Default false for back-compat-safe parsing by older clients. Default: False.
        landing_first (bool | Unset): When true, unauthenticated visits to '/' are redirected to '/login' as the product
            landing page. Default false (search catalog is the root). Default: False.
        password_login_enabled (bool | Unset): When false, password login is disabled for users without manage_settings.
            Default true for back-compat-safe parsing by older clients. Default: True.
    """

    registration_enabled: bool
    allow_signup: bool | Unset = False
    auth_methods: list[str] | Unset = UNSET
    banner_color: str | Unset = "warning"
    banner_enabled: bool | Unset = False
    banner_text: str | Unset = ""
    demo_mode: bool | Unset = False
    email_verification_required: bool | Unset = False
    landing_first: bool | Unset = False
    password_login_enabled: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        registration_enabled = self.registration_enabled

        allow_signup = self.allow_signup

        auth_methods: list[str] | Unset = UNSET
        if not isinstance(self.auth_methods, Unset):
            auth_methods = self.auth_methods

        banner_color = self.banner_color

        banner_enabled = self.banner_enabled

        banner_text = self.banner_text

        demo_mode = self.demo_mode

        email_verification_required = self.email_verification_required

        landing_first = self.landing_first

        password_login_enabled = self.password_login_enabled

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "registration_enabled": registration_enabled,
            }
        )
        if allow_signup is not UNSET:
            field_dict["allow_signup"] = allow_signup
        if auth_methods is not UNSET:
            field_dict["auth_methods"] = auth_methods
        if banner_color is not UNSET:
            field_dict["banner_color"] = banner_color
        if banner_enabled is not UNSET:
            field_dict["banner_enabled"] = banner_enabled
        if banner_text is not UNSET:
            field_dict["banner_text"] = banner_text
        if demo_mode is not UNSET:
            field_dict["demo_mode"] = demo_mode
        if email_verification_required is not UNSET:
            field_dict["email_verification_required"] = email_verification_required
        if landing_first is not UNSET:
            field_dict["landing_first"] = landing_first
        if password_login_enabled is not UNSET:
            field_dict["password_login_enabled"] = password_login_enabled

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        registration_enabled = d.pop("registration_enabled")

        allow_signup = d.pop("allow_signup", UNSET)

        auth_methods = cast(list[str], d.pop("auth_methods", UNSET))

        banner_color = d.pop("banner_color", UNSET)

        banner_enabled = d.pop("banner_enabled", UNSET)

        banner_text = d.pop("banner_text", UNSET)

        demo_mode = d.pop("demo_mode", UNSET)

        email_verification_required = d.pop("email_verification_required", UNSET)

        landing_first = d.pop("landing_first", UNSET)

        password_login_enabled = d.pop("password_login_enabled", UNSET)

        config_response = cls(
            registration_enabled=registration_enabled,
            allow_signup=allow_signup,
            auth_methods=auth_methods,
            banner_color=banner_color,
            banner_enabled=banner_enabled,
            banner_text=banner_text,
            demo_mode=demo_mode,
            email_verification_required=email_verification_required,
            landing_first=landing_first,
            password_login_enabled=password_login_enabled,
        )

        config_response.additional_properties = d
        return config_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties

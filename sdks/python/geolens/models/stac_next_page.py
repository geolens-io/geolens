from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.stac_next_page_method import check_stac_next_page_method
from ..models.stac_next_page_method import StacNextPageMethod
from typing import cast

if TYPE_CHECKING:
    from ..models.stac_next_page_body_type_0 import StacNextPageBodyType0


T = TypeVar("T", bound="StacNextPage")


@_attrs_define
class StacNextPage:
    """A STAC ``rel="next"`` link, echoed back to fetch the following page.

    Attributes:
        method (StacNextPageMethod): HTTP method of the link.
        href (str): Absolute URL of the next page. It must share the origin of the catalog URL it came from; any other
            origin is refused.
        body (None | StacNextPageBodyType0 | Unset): JSON body of a POST link.
        merge (bool | Unset): Whether the body is merged into the original search body. Default: False.
        signature (None | str | Unset): Server-issued signature of this link for the catalog URL and collections it was
            issued for. Echo it back unchanged; a link without a matching signature is refused.
    """

    method: StacNextPageMethod
    href: str
    body: None | StacNextPageBodyType0 | Unset = UNSET
    merge: bool | Unset = False
    signature: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.stac_next_page_body_type_0 import StacNextPageBodyType0

        method: str = self.method

        href = self.href

        body: dict[str, Any] | None | Unset
        if isinstance(self.body, Unset):
            body = UNSET
        elif isinstance(self.body, StacNextPageBodyType0):
            body = self.body.to_dict()
        else:
            body = self.body

        merge = self.merge

        signature: None | str | Unset
        if isinstance(self.signature, Unset):
            signature = UNSET
        else:
            signature = self.signature

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "method": method,
                "href": href,
            }
        )
        if body is not UNSET:
            field_dict["body"] = body
        if merge is not UNSET:
            field_dict["merge"] = merge
        if signature is not UNSET:
            field_dict["signature"] = signature

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_next_page_body_type_0 import StacNextPageBodyType0

        d = dict(src_dict)
        method = check_stac_next_page_method(d.pop("method"))

        href = d.pop("href")

        def _parse_body(data: object) -> None | StacNextPageBodyType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                body_type_0 = StacNextPageBodyType0.from_dict(data)

                return body_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StacNextPageBodyType0 | Unset, data)

        body = _parse_body(d.pop("body", UNSET))

        merge = d.pop("merge", UNSET)

        def _parse_signature(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        signature = _parse_signature(d.pop("signature", UNSET))

        stac_next_page = cls(
            method=method,
            href=href,
            body=body,
            merge=merge,
            signature=signature,
        )

        stac_next_page.additional_properties = d
        return stac_next_page

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

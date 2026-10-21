from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import Literal, cast


T = TypeVar("T", bound="VectorTileToken")


@_attrs_define
class VectorTileToken:
    """
    Attributes:
        kind (Literal['vector']):
        sig (str):
        exp (int):
        scope (str):
        expires_in (int):
        tile_url_template (str): Signed vector tile URL template, relative to the API root, with `{z}`, `{x}` and `{y}`
            left for the client to fill in.
    """

    kind: Literal["vector"]
    sig: str
    exp: int
    scope: str
    expires_in: int
    tile_url_template: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        sig = self.sig

        exp = self.exp

        scope = self.scope

        expires_in = self.expires_in

        tile_url_template = self.tile_url_template

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "kind": kind,
                "sig": sig,
                "exp": exp,
                "scope": scope,
                "expires_in": expires_in,
                "tile_url_template": tile_url_template,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        kind = cast(Literal["vector"], d.pop("kind"))
        if kind != "vector":
            raise ValueError(f"kind must match const 'vector', got '{kind}'")

        sig = d.pop("sig")

        exp = d.pop("exp")

        scope = d.pop("scope")

        expires_in = d.pop("expires_in")

        tile_url_template = d.pop("tile_url_template")

        vector_tile_token = cls(
            kind=kind,
            sig=sig,
            exp=exp,
            scope=scope,
            expires_in=expires_in,
            tile_url_template=tile_url_template,
        )

        vector_tile_token.additional_properties = d
        return vector_tile_token

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

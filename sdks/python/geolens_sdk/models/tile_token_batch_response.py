from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.tile_token_batch_response_tokens import TileTokenBatchResponseTokens


T = TypeVar("T", bound="TileTokenBatchResponse")


@_attrs_define
class TileTokenBatchResponse:
    """Batch response mapping dataset_id (string) to token or error.

    Each entry is either a VectorTileToken, a RasterTileToken, or a
    ``{"error": "..."}`` object describing why the token could not be
    generated (404 dataset, 403 forbidden, etc.). The batch call itself
    succeeds even if individual datasets fail — clients should check each
    entry for the ``error`` key.

        Attributes:
            tokens (TileTokenBatchResponseTokens):
    """

    tokens: TileTokenBatchResponseTokens
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tokens = self.tokens.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tokens": tokens,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.tile_token_batch_response_tokens import (
            TileTokenBatchResponseTokens,
        )

        d = dict(src_dict)
        tokens = TileTokenBatchResponseTokens.from_dict(d.pop("tokens"))

        tile_token_batch_response = cls(
            tokens=tokens,
        )

        tile_token_batch_response.additional_properties = d
        return tile_token_batch_response

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

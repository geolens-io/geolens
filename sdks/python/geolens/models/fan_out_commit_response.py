from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.fan_out_layer_result import FanOutLayerResult


T = TypeVar("T", bound="FanOutCommitResponse")


@_attrs_define
class FanOutCommitResponse:
    """Response from POST /ingest/commit-fan-out/{job_id}.

    Attributes:
        fan_out_id (UUID): The original job_id (parent). Use for client-side correlation.
        results (list[FanOutLayerResult]): Per-layer outcomes in the same order as the request layers.
        origin_link_loss (list[str] | Unset): Reasons the ArcGIS item link was dropped: 'item_id_invalid',
            'portal_url_invalid', 'portal_url_domain_mismatch' or 'origin_link_unsupported'. Empty when nothing was dropped.
    """

    fan_out_id: UUID
    results: list[FanOutLayerResult]
    origin_link_loss: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        fan_out_id = str(self.fan_out_id)

        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        origin_link_loss: list[str] | Unset = UNSET
        if not isinstance(self.origin_link_loss, Unset):
            origin_link_loss = self.origin_link_loss

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "fan_out_id": fan_out_id,
                "results": results,
            }
        )
        if origin_link_loss is not UNSET:
            field_dict["origin_link_loss"] = origin_link_loss

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.fan_out_layer_result import FanOutLayerResult

        d = dict(src_dict)
        fan_out_id = UUID(d.pop("fan_out_id"))

        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = FanOutLayerResult.from_dict(results_item_data)

            results.append(results_item)

        origin_link_loss = cast(list[str], d.pop("origin_link_loss", UNSET))

        fan_out_commit_response = cls(
            fan_out_id=fan_out_id,
            results=results,
            origin_link_loss=origin_link_loss,
        )

        fan_out_commit_response.additional_properties = d
        return fan_out_commit_response

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

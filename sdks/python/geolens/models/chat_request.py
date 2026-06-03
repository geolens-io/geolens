from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.chat_history_message import ChatHistoryMessage
    from ..models.chat_map_layer import ChatMapLayer


T = TypeVar("T", bound="ChatRequest")


@_attrs_define
class ChatRequest:
    """
    Attributes:
        layers (list[ChatMapLayer]):
        map_id (str):
        message (str):
        history (list[ChatHistoryMessage] | Unset):
        language (None | str | Unset):
    """

    layers: list[ChatMapLayer]
    map_id: str
    message: str
    history: list[ChatHistoryMessage] | Unset = UNSET
    language: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        map_id = self.map_id

        message = self.message

        history: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.history, Unset):
            history = []
            for history_item_data in self.history:
                history_item = history_item_data.to_dict()
                history.append(history_item)

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layers": layers,
                "map_id": map_id,
                "message": message,
            }
        )
        if history is not UNSET:
            field_dict["history"] = history
        if language is not UNSET:
            field_dict["language"] = language

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.chat_history_message import ChatHistoryMessage
        from ..models.chat_map_layer import ChatMapLayer

        d = dict(src_dict)
        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = ChatMapLayer.from_dict(layers_item_data)

            layers.append(layers_item)

        map_id = d.pop("map_id")

        message = d.pop("message")

        _history = d.pop("history", UNSET)
        history: list[ChatHistoryMessage] | Unset = UNSET
        if _history is not UNSET:
            history = []
            for history_item_data in _history:
                history_item = ChatHistoryMessage.from_dict(history_item_data)

                history.append(history_item)

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        chat_request = cls(
            layers=layers,
            map_id=map_id,
            message=message,
            history=history,
            language=language,
        )

        chat_request.additional_properties = d
        return chat_request

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

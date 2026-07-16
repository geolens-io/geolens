from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.chat_history_message import ChatHistoryMessage


T = TypeVar("T", bound="DatasetChatRequest")


@_attrs_define
class DatasetChatRequest:
    """Dataset-scoped chat: no map, no client-supplied layer state.

    The server resolves ALL dataset context (table name, columns, samples)
    authoritatively from the DB — the client only names the dataset.

        Attributes:
            dataset_id (str):
            message (str):
            history (list[ChatHistoryMessage] | Unset):
            language (None | str | Unset):
    """

    dataset_id: str
    message: str
    history: list[ChatHistoryMessage] | Unset = UNSET
    language: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = self.dataset_id

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
                "dataset_id": dataset_id,
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

        d = dict(src_dict)
        dataset_id = d.pop("dataset_id")

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

        dataset_chat_request = cls(
            dataset_id=dataset_id,
            message=message,
            history=history,
            language=language,
        )

        dataset_chat_request.additional_properties = d
        return dataset_chat_request

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

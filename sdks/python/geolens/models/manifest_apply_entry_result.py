from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.manifest_apply_entry_result_action import (
    check_manifest_apply_entry_result_action,
)
from ..models.manifest_apply_entry_result_action import ManifestApplyEntryResultAction
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.manifest_dataset_links import ManifestDatasetLinks
    from ..models.manifest_message import ManifestMessage


T = TypeVar("T", bound="ManifestApplyEntryResult")


@_attrs_define
class ManifestApplyEntryResult:
    """
    Attributes:
        dataset_key (str):
        action (ManifestApplyEntryResultAction): What apply did with the entry. `blocked` means the entry is unchanged
            since its last apply, whose replacement is held for review, so nothing was queued. Accept it by sending `run_id`
            as `accept_blocked_run_id` to the dataset's refresh endpoint, or change the entry.
        message (str):
        job_id (None | Unset | UUID):
        dataset_id (None | Unset | UUID):
        run_id (None | Unset | UUID): The blocked refresh run to accept, when action is `blocked`.
        review_reasons (list[str] | Unset): Why the blocked run needs review, when action is `blocked`.
        errors (list[str] | Unset):
        messages (list[ManifestMessage] | None | Unset): Coded messages for the entry. Left out in manifest version 1.
        visibility (None | str | Unset): Who can see the dataset once the entry's job finishes: the level the entry
            writes, or the stored one when it writes none. Null when the entry failed or the dataset can't be read. Left out
            in manifest version 1.
        links (ManifestDatasetLinks | None | Unset): Links to the dataset. Null when there is no dataset yet or the
            caller can't read it. Left out in manifest version 1.
    """

    dataset_key: str
    action: ManifestApplyEntryResultAction
    message: str
    job_id: None | Unset | UUID = UNSET
    dataset_id: None | Unset | UUID = UNSET
    run_id: None | Unset | UUID = UNSET
    review_reasons: list[str] | Unset = UNSET
    errors: list[str] | Unset = UNSET
    messages: list[ManifestMessage] | None | Unset = UNSET
    visibility: None | str | Unset = UNSET
    links: ManifestDatasetLinks | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_dataset_links import ManifestDatasetLinks

        dataset_key = self.dataset_key

        action: str = self.action

        message = self.message

        job_id: None | str | Unset
        if isinstance(self.job_id, Unset):
            job_id = UNSET
        elif isinstance(self.job_id, UUID):
            job_id = str(self.job_id)
        else:
            job_id = self.job_id

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        run_id: None | str | Unset
        if isinstance(self.run_id, Unset):
            run_id = UNSET
        elif isinstance(self.run_id, UUID):
            run_id = str(self.run_id)
        else:
            run_id = self.run_id

        review_reasons: list[str] | Unset = UNSET
        if not isinstance(self.review_reasons, Unset):
            review_reasons = self.review_reasons

        errors: list[str] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = self.errors

        messages: list[dict[str, Any]] | None | Unset
        if isinstance(self.messages, Unset):
            messages = UNSET
        elif isinstance(self.messages, list):
            messages = []
            for messages_type_0_item_data in self.messages:
                messages_type_0_item = messages_type_0_item_data.to_dict()
                messages.append(messages_type_0_item)

        else:
            messages = self.messages

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        else:
            visibility = self.visibility

        links: dict[str, Any] | None | Unset
        if isinstance(self.links, Unset):
            links = UNSET
        elif isinstance(self.links, ManifestDatasetLinks):
            links = self.links.to_dict()
        else:
            links = self.links

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_key": dataset_key,
                "action": action,
                "message": message,
            }
        )
        if job_id is not UNSET:
            field_dict["job_id"] = job_id
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if run_id is not UNSET:
            field_dict["run_id"] = run_id
        if review_reasons is not UNSET:
            field_dict["review_reasons"] = review_reasons
        if errors is not UNSET:
            field_dict["errors"] = errors
        if messages is not UNSET:
            field_dict["messages"] = messages
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if links is not UNSET:
            field_dict["links"] = links

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_dataset_links import ManifestDatasetLinks
        from ..models.manifest_message import ManifestMessage

        d = dict(src_dict)
        dataset_key = d.pop("dataset_key")

        action = check_manifest_apply_entry_result_action(d.pop("action"))

        message = d.pop("message")

        def _parse_job_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                job_id_type_0 = UUID(data)

                return job_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        job_id = _parse_job_id(d.pop("job_id", UNSET))

        def _parse_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        def _parse_run_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                run_id_type_0 = UUID(data)

                return run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        run_id = _parse_run_id(d.pop("run_id", UNSET))

        review_reasons = cast(list[str], d.pop("review_reasons", UNSET))

        errors = cast(list[str], d.pop("errors", UNSET))

        def _parse_messages(data: object) -> list[ManifestMessage] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                messages_type_0 = []
                _messages_type_0 = data
                for messages_type_0_item_data in _messages_type_0:
                    messages_type_0_item = ManifestMessage.from_dict(
                        messages_type_0_item_data
                    )

                    messages_type_0.append(messages_type_0_item)

                return messages_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ManifestMessage] | None | Unset, data)

        messages = _parse_messages(d.pop("messages", UNSET))

        def _parse_visibility(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        def _parse_links(data: object) -> ManifestDatasetLinks | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                links_type_0 = ManifestDatasetLinks.from_dict(data)

                return links_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestDatasetLinks | None | Unset, data)

        links = _parse_links(d.pop("links", UNSET))

        manifest_apply_entry_result = cls(
            dataset_key=dataset_key,
            action=action,
            message=message,
            job_id=job_id,
            dataset_id=dataset_id,
            run_id=run_id,
            review_reasons=review_reasons,
            errors=errors,
            messages=messages,
            visibility=visibility,
            links=links,
        )

        manifest_apply_entry_result.additional_properties = d
        return manifest_apply_entry_result

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

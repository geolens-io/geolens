from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="BackfillResponse")


@_attrs_define
class BackfillResponse:
    """
    Attributes:
        processed (int): Number of records processed in this backfill batch.
        created (int): Number of new embeddings created.
        skipped (int): Number of records skipped because an embedding already existed.
        errors (int): Number of records that failed during embedding generation.
    """

    processed: int
    created: int
    skipped: int
    errors: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        processed = self.processed

        created = self.created

        skipped = self.skipped

        errors = self.errors

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "processed": processed,
                "created": created,
                "skipped": skipped,
                "errors": errors,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        processed = d.pop("processed")

        created = d.pop("created")

        skipped = d.pop("skipped")

        errors = d.pop("errors")

        backfill_response = cls(
            processed=processed,
            created=created,
            skipped=skipped,
            errors=errors,
        )

        backfill_response.additional_properties = d
        return backfill_response

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

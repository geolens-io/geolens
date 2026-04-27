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
        created (int): Number of new embeddings created.
        errors (int): Number of records that failed during embedding generation.
        processed (int): Number of records processed in this backfill batch.
        skipped (int): Number of records skipped because an embedding already existed.
    """

    created: int
    errors: int
    processed: int
    skipped: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created = self.created

        errors = self.errors

        processed = self.processed

        skipped = self.skipped

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created": created,
                "errors": errors,
                "processed": processed,
                "skipped": skipped,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created = d.pop("created")

        errors = d.pop("errors")

        processed = d.pop("processed")

        skipped = d.pop("skipped")

        backfill_response = cls(
            created=created,
            errors=errors,
            processed=processed,
            skipped=skipped,
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

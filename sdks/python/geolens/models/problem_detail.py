from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1
    from ..models.problem_detail_shared_maps_item import ProblemDetailSharedMapsItem


T = TypeVar("T", bound="ProblemDetail")


@_attrs_define
class ProblemDetail:
    """
    Attributes:
        title (str):
        status (int):
        detail (list[Any] | ProblemDetailDetailType1 | str):
        type_ (str | Unset):  Default: 'about:blank'.
        code (str | Unset): A machine-readable code for the problem, on the errors that carry one, such as
            `catalog_lock_conflict` on a 409 for a row another request holds. Absent otherwise.
        action (str | Unset): The refused change, on a `dataset_in_shared_maps` 422: `unpublish` or
            `restrict_visibility`. Absent otherwise.
        shared_maps (list[ProblemDetailSharedMapsItem] | Unset): The shared maps behind a `dataset_in_shared_maps` 422,
            as `{"id", "name"}` pairs. Absent otherwise.
    """

    title: str
    status: int
    detail: list[Any] | ProblemDetailDetailType1 | str
    type_: str | Unset = "about:blank"
    code: str | Unset = UNSET
    action: str | Unset = UNSET
    shared_maps: list[ProblemDetailSharedMapsItem] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1

        title = self.title

        status = self.status

        detail: dict[str, Any] | list[Any] | str
        if isinstance(self.detail, ProblemDetailDetailType1):
            detail = self.detail.to_dict()
        elif isinstance(self.detail, list):
            detail = self.detail

        else:
            detail = self.detail

        type_ = self.type_

        code = self.code

        action = self.action

        shared_maps: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.shared_maps, Unset):
            shared_maps = []
            for shared_maps_item_data in self.shared_maps:
                shared_maps_item = shared_maps_item_data.to_dict()
                shared_maps.append(shared_maps_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "status": status,
                "detail": detail,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if code is not UNSET:
            field_dict["code"] = code
        if action is not UNSET:
            field_dict["action"] = action
        if shared_maps is not UNSET:
            field_dict["shared_maps"] = shared_maps

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1
        from ..models.problem_detail_shared_maps_item import ProblemDetailSharedMapsItem

        d = dict(src_dict)
        title = d.pop("title")

        status = d.pop("status")

        def _parse_detail(data: object) -> list[Any] | ProblemDetailDetailType1 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                detail_type_1 = ProblemDetailDetailType1.from_dict(data)

                return detail_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, list):
                    raise TypeError()
                detail_type_2 = cast(list[Any], data)

                return detail_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | ProblemDetailDetailType1 | str, data)

        detail = _parse_detail(d.pop("detail"))

        type_ = d.pop("type", UNSET)

        code = d.pop("code", UNSET)

        action = d.pop("action", UNSET)

        _shared_maps = d.pop("shared_maps", UNSET)
        shared_maps: list[ProblemDetailSharedMapsItem] | Unset = UNSET
        if _shared_maps is not UNSET:
            shared_maps = []
            for shared_maps_item_data in _shared_maps:
                shared_maps_item = ProblemDetailSharedMapsItem.from_dict(
                    shared_maps_item_data
                )

                shared_maps.append(shared_maps_item)

        problem_detail = cls(
            title=title,
            status=status,
            detail=detail,
            type_=type_,
            code=code,
            action=action,
            shared_maps=shared_maps,
        )

        problem_detail.additional_properties = d
        return problem_detail

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

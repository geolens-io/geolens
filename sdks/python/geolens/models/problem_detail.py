from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1


T = TypeVar("T", bound="ProblemDetail")


@_attrs_define
class ProblemDetail:
    """
    Attributes:
        detail (list[Any] | ProblemDetailDetailType1 | str):
        status (int):
        title (str):
        type_ (str | Unset):  Default: 'about:blank'.
    """

    detail: list[Any] | ProblemDetailDetailType1 | str
    status: int
    title: str
    type_: str | Unset = "about:blank"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1

        detail: dict[str, Any] | list[Any] | str
        if isinstance(self.detail, ProblemDetailDetailType1):
            detail = self.detail.to_dict()
        elif isinstance(self.detail, list):
            detail = self.detail

        else:
            detail = self.detail

        status = self.status

        title = self.title

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "detail": detail,
                "status": status,
                "title": title,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.problem_detail_detail_type_1 import ProblemDetailDetailType1

        d = dict(src_dict)

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

        status = d.pop("status")

        title = d.pop("title")

        type_ = d.pop("type", UNSET)

        problem_detail = cls(
            detail=detail,
            status=status,
            title=title,
            type_=type_,
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

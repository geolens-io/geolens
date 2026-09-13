from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.refresh_verification_count_status import (
    check_refresh_verification_count_status,
)
from ..models.refresh_verification_count_status import RefreshVerificationCountStatus
from ..models.refresh_verification_decision import check_refresh_verification_decision
from ..models.refresh_verification_decision import RefreshVerificationDecision
from ..models.refresh_verification_identity_check import (
    check_refresh_verification_identity_check,
)
from ..models.refresh_verification_identity_check import (
    RefreshVerificationIdentityCheck,
)
from ..models.refresh_verification_review_reasons_item import (
    check_refresh_verification_review_reasons_item,
)
from ..models.refresh_verification_review_reasons_item import (
    RefreshVerificationReviewReasonsItem,
)
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.refresh_verification_source_binding import (
        RefreshVerificationSourceBinding,
    )


T = TypeVar("T", bound="RefreshVerification")


@_attrs_define
class RefreshVerification:
    """
    Attributes:
        decision (RefreshVerificationDecision):
        source_binding (RefreshVerificationSourceBinding):
        source_count (int | None):
        fetched_count (int | None):
        count_status (RefreshVerificationCountStatus):
        identity_check (RefreshVerificationIdentityCheck):
        review_reasons (list[RefreshVerificationReviewReasonsItem]):
        review_fingerprint (None | str):
        accepted_blocked_run_id (None | UUID):
        content_digest (None | str | Unset):
        staged_geometry_type (None | str | Unset):
        staged_srid (int | None | Unset):
        staged_coordinate_dimension (int | None | Unset):
        acceptance_consumed_by_run_id (None | Unset | UUID):
    """

    decision: RefreshVerificationDecision
    source_binding: RefreshVerificationSourceBinding
    source_count: int | None
    fetched_count: int | None
    count_status: RefreshVerificationCountStatus
    identity_check: RefreshVerificationIdentityCheck
    review_reasons: list[RefreshVerificationReviewReasonsItem]
    review_fingerprint: None | str
    accepted_blocked_run_id: None | UUID
    content_digest: None | str | Unset = UNSET
    staged_geometry_type: None | str | Unset = UNSET
    staged_srid: int | None | Unset = UNSET
    staged_coordinate_dimension: int | None | Unset = UNSET
    acceptance_consumed_by_run_id: None | Unset | UUID = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        decision: str = self.decision

        source_binding = self.source_binding.to_dict()

        source_count: int | None
        source_count = self.source_count

        fetched_count: int | None
        fetched_count = self.fetched_count

        count_status: str = self.count_status

        identity_check: str = self.identity_check

        review_reasons = []
        for review_reasons_item_data in self.review_reasons:
            review_reasons_item: str = review_reasons_item_data
            review_reasons.append(review_reasons_item)

        review_fingerprint: None | str
        review_fingerprint = self.review_fingerprint

        accepted_blocked_run_id: None | str
        if isinstance(self.accepted_blocked_run_id, UUID):
            accepted_blocked_run_id = str(self.accepted_blocked_run_id)
        else:
            accepted_blocked_run_id = self.accepted_blocked_run_id

        content_digest: None | str | Unset
        if isinstance(self.content_digest, Unset):
            content_digest = UNSET
        else:
            content_digest = self.content_digest

        staged_geometry_type: None | str | Unset
        if isinstance(self.staged_geometry_type, Unset):
            staged_geometry_type = UNSET
        else:
            staged_geometry_type = self.staged_geometry_type

        staged_srid: int | None | Unset
        if isinstance(self.staged_srid, Unset):
            staged_srid = UNSET
        else:
            staged_srid = self.staged_srid

        staged_coordinate_dimension: int | None | Unset
        if isinstance(self.staged_coordinate_dimension, Unset):
            staged_coordinate_dimension = UNSET
        else:
            staged_coordinate_dimension = self.staged_coordinate_dimension

        acceptance_consumed_by_run_id: None | str | Unset
        if isinstance(self.acceptance_consumed_by_run_id, Unset):
            acceptance_consumed_by_run_id = UNSET
        elif isinstance(self.acceptance_consumed_by_run_id, UUID):
            acceptance_consumed_by_run_id = str(self.acceptance_consumed_by_run_id)
        else:
            acceptance_consumed_by_run_id = self.acceptance_consumed_by_run_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "decision": decision,
                "source_binding": source_binding,
                "source_count": source_count,
                "fetched_count": fetched_count,
                "count_status": count_status,
                "identity_check": identity_check,
                "review_reasons": review_reasons,
                "review_fingerprint": review_fingerprint,
                "accepted_blocked_run_id": accepted_blocked_run_id,
            }
        )
        if content_digest is not UNSET:
            field_dict["content_digest"] = content_digest
        if staged_geometry_type is not UNSET:
            field_dict["staged_geometry_type"] = staged_geometry_type
        if staged_srid is not UNSET:
            field_dict["staged_srid"] = staged_srid
        if staged_coordinate_dimension is not UNSET:
            field_dict["staged_coordinate_dimension"] = staged_coordinate_dimension
        if acceptance_consumed_by_run_id is not UNSET:
            field_dict["acceptance_consumed_by_run_id"] = acceptance_consumed_by_run_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.refresh_verification_source_binding import (
            RefreshVerificationSourceBinding,
        )

        d = dict(src_dict)
        decision = check_refresh_verification_decision(d.pop("decision"))

        source_binding = RefreshVerificationSourceBinding.from_dict(
            d.pop("source_binding")
        )

        def _parse_source_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        source_count = _parse_source_count(d.pop("source_count"))

        def _parse_fetched_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        fetched_count = _parse_fetched_count(d.pop("fetched_count"))

        count_status = check_refresh_verification_count_status(d.pop("count_status"))

        identity_check = check_refresh_verification_identity_check(
            d.pop("identity_check")
        )

        review_reasons = []
        _review_reasons = d.pop("review_reasons")
        for review_reasons_item_data in _review_reasons:
            review_reasons_item = check_refresh_verification_review_reasons_item(
                review_reasons_item_data
            )

            review_reasons.append(review_reasons_item)

        def _parse_review_fingerprint(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        review_fingerprint = _parse_review_fingerprint(d.pop("review_fingerprint"))

        def _parse_accepted_blocked_run_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                accepted_blocked_run_id_type_0 = UUID(data)

                return accepted_blocked_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        accepted_blocked_run_id = _parse_accepted_blocked_run_id(
            d.pop("accepted_blocked_run_id")
        )

        def _parse_content_digest(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_digest = _parse_content_digest(d.pop("content_digest", UNSET))

        def _parse_staged_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        staged_geometry_type = _parse_staged_geometry_type(
            d.pop("staged_geometry_type", UNSET)
        )

        def _parse_staged_srid(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        staged_srid = _parse_staged_srid(d.pop("staged_srid", UNSET))

        def _parse_staged_coordinate_dimension(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        staged_coordinate_dimension = _parse_staged_coordinate_dimension(
            d.pop("staged_coordinate_dimension", UNSET)
        )

        def _parse_acceptance_consumed_by_run_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                acceptance_consumed_by_run_id_type_0 = UUID(data)

                return acceptance_consumed_by_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        acceptance_consumed_by_run_id = _parse_acceptance_consumed_by_run_id(
            d.pop("acceptance_consumed_by_run_id", UNSET)
        )

        refresh_verification = cls(
            decision=decision,
            source_binding=source_binding,
            source_count=source_count,
            fetched_count=fetched_count,
            count_status=count_status,
            identity_check=identity_check,
            review_reasons=review_reasons,
            review_fingerprint=review_fingerprint,
            accepted_blocked_run_id=accepted_blocked_run_id,
            content_digest=content_digest,
            staged_geometry_type=staged_geometry_type,
            staged_srid=staged_srid,
            staged_coordinate_dimension=staged_coordinate_dimension,
            acceptance_consumed_by_run_id=acceptance_consumed_by_run_id,
        )

        refresh_verification.additional_properties = d
        return refresh_verification

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

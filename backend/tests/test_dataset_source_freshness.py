"""Source freshness from update_frequency, last_refreshed_at, origin (#1224).

Five properties this suite holds:

1. The mapping is total and deterministic. ``now`` and ``origin`` are
   arguments, so every threshold is pinned without freezing a clock, and every
   value of the ISO 19115 vocabulary has an asserted answer.
2. An origin nothing can refresh never reports a deadline. ``created``
   datasets are stamped with ``last_refreshed_at`` at creation
   (``service_create.py``) and answer 409 ``refresh_not_applicable``, so
   without the gate an old sketch layer would read "overdue" and name an
   action that does not exist for it.
3. The vocabulary the mapping knows about is the vocabulary the database
   accepts, and the origins it classifies are the origins that exist. A value
   added to ``chk_records_update_frequency`` or to ``ORIGIN_KINDS`` with no
   decision recorded here would otherwise render as ``unknown`` forever, which
   is a legitimate-looking state and therefore silent.
4. Source freshness reaches both response surfaces, and they agree. A dataset
   detail page and a catalog card compute the same thing from the same
   columns; two independent implementations is the bug ADR-002 Decision 2
   exists to prevent.
5. Nothing is written. No column, no PATCHable field. The whole point is that
   the state derives from live columns, so a stored copy could only go stale.

Boundary cases are asserted in both directions: exactly one period is fresh
AND one second past it is due. A one-sided assertion cannot notice the
comparison flipping to inclusive.

Note the name throughout: SOURCE freshness. ``frontend/src/lib/quality-
freshness.ts`` measures the quality score's ``computed_at`` against the same
``update_frequency`` with different thresholds and a different state set, and
the two must never be read as one thing.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.schemas import DatasetMeta
from app.modules.catalog.datasets.domain.source_freshness import (
    DUE,
    FRESH,
    FREQUENCY_PERIOD_DAYS,
    NON_REFRESHABLE_ORIGINS,
    OVERDUE,
    OVERDUE_PERIOD_MULTIPLE,
    REFRESHABLE_ORIGINS,
    SOURCE_FRESHNESS_VALUES,
    UNKNOWN,
    UNSCHEDULED_FREQUENCIES,
    UPDATE_FREQUENCY_VOCABULARY,
    compute_source_freshness,
)
from app.modules.catalog.search.schemas import OGCRecordProperties
from app.platform.dataset_origin import ORIGIN_KINDS
from tests.factories import create_dataset as _create_dataset, get_user_id

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)

# The four vocabulary values that declare no cadence. Listed literally rather
# than reusing UNSCHEDULED_FREQUENCIES, which is derived from the same table
# the mapping reads: deriving the expectation from the implementation would
# make this assertion true by construction.
_UNSCHEDULED = ("asNeeded", "irregular", "notPlanned", "unknown")


def _freshness(
    last_refreshed_at: datetime | None,
    update_frequency: str | None,
    now: datetime,
    origin: str | None = "upload",
) -> str:
    """``compute_source_freshness`` with a refreshable origin by default.

    The threshold tests are not about origin, and repeating ``origin="upload"``
    across every one of them would bury the argument that IS under test.
    ``TestOriginApplicabilityGate`` calls the real function directly.
    """
    return compute_source_freshness(
        last_refreshed_at, update_frequency, now, origin=origin
    )


class TestPureMapping:
    """(last_refreshed_at, update_frequency, now, origin) -> one of four strings."""

    @pytest.mark.parametrize(
        ("frequency", "period_days"),
        sorted(FREQUENCY_PERIOD_DAYS.items()),
    )
    def test_each_cadence_walks_fresh_due_overdue(
        self, frequency: str, period_days: int
    ) -> None:
        """One period is the fresh/due line, two the due/overdue line.

        Both sides of both lines, for every cadence: a strict comparison that
        became inclusive would keep passing against the "past the line" case
        alone, and an on-time refresh lands exactly ON the line.
        """
        period = timedelta(days=period_days)
        second = timedelta(seconds=1)

        cases = (
            (timedelta(0), FRESH),
            (period - second, FRESH),
            (period, FRESH),
            (period + second, DUE),
            (period * OVERDUE_PERIOD_MULTIPLE - second, DUE),
            (period * OVERDUE_PERIOD_MULTIPLE, DUE),
            (period * OVERDUE_PERIOD_MULTIPLE + second, OVERDUE),
            (period * 100, OVERDUE),
        )
        for age, expected in cases:
            assert _freshness(NOW - age, frequency, NOW) == expected, (
                f"{frequency} at age {age} should be {expected}"
            )

    @pytest.mark.parametrize("frequency", _UNSCHEDULED)
    def test_unscheduled_frequencies_are_unknown_at_any_age(
        self, frequency: str
    ) -> None:
        """No cadence declared means no age can be late against it."""
        for age in (timedelta(0), timedelta(days=1), timedelta(days=10_000)):
            assert _freshness(NOW - age, frequency, NOW) == UNKNOWN

    def test_missing_frequency_is_unknown(self) -> None:
        assert _freshness(NOW - timedelta(days=999), None, NOW) == UNKNOWN

    def test_missing_last_refreshed_at_is_unknown(self) -> None:
        assert _freshness(None, "daily", NOW) == UNKNOWN
        # Both missing at once, the state of a dataset nobody has touched.
        assert _freshness(None, None, NOW) == UNKNOWN

    def test_unrecognised_frequency_string_is_unknown(self) -> None:
        """A value the CHECK constraint would reject still cannot raise.

        Pre-CHECK rows and future vocabulary both arrive here as a string
        nothing maps; a KeyError on a plain dataset GET would be worse than a
        conservative answer. The drift guard below is what keeps this from
        being how a real new vocabulary value gets handled.
        """
        assert _freshness(NOW - timedelta(days=999), "fortnightly", NOW) == (UNKNOWN)
        assert _freshness(NOW, "", NOW) == UNKNOWN

    def test_a_future_refresh_timestamp_is_fresh(self) -> None:
        """Clock skew between the app and the database must not read as late."""
        assert _freshness(NOW + timedelta(days=5), "daily", NOW) == FRESH

    def test_naive_datetimes_are_read_as_utc(self) -> None:
        """The only naive datetimes this codebase makes are already UTC.

        Coercing keeps a stray naive value from turning a read path into a
        500, and the answer it produces is the same one the aware pair gives.
        """
        naive_now = NOW.replace(tzinfo=None)
        naive_old = (NOW - timedelta(days=3)).replace(tzinfo=None)
        assert _freshness(naive_old, "daily", naive_now) == OVERDUE
        # Mixed awareness, the shape that actually raises without the coercion.
        assert _freshness(naive_old, "daily", NOW) == OVERDUE
        assert _freshness(NOW - timedelta(days=3), "daily", naive_now) == (OVERDUE)

    def test_the_mapping_only_ever_returns_a_declared_value(self) -> None:
        for frequency in sorted(UPDATE_FREQUENCY_VOCABULARY) + [None, "nonsense"]:
            for age_days in (0, 1, 8, 40, 200, 400, 5000):
                result = _freshness(NOW - timedelta(days=age_days), frequency, NOW)
                assert result in SOURCE_FRESHNESS_VALUES


class TestOriginApplicabilityGate:
    """An origin nothing can refresh never reports a deadline."""

    @pytest.mark.parametrize("frequency", sorted(FREQUENCY_PERIOD_DAYS))
    @pytest.mark.parametrize("age_days", [0, 400, 5000])
    def test_created_origin_is_unknown_at_every_age_and_cadence(
        self, frequency: str, age_days: int
    ) -> None:
        """The whole reason origin is a parameter.

        ``service_create.py`` stamps every new dataset with
        ``last_refreshed_at``, and migration 0036 backfills a floor for older
        rows, so a sketch layer always has a timestamp. ADR-002 Decision 5a
        gives ``created`` a 409 ``refresh_not_applicable``, so any answer other
        than ``unknown`` here points the user at an action that does not exist.
        """
        assert (
            compute_source_freshness(
                NOW - timedelta(days=age_days), frequency, NOW, origin="created"
            )
            == UNKNOWN
        )

    @pytest.mark.parametrize("origin", sorted(REFRESHABLE_ORIGINS))
    def test_every_refreshable_origin_still_reports_a_deadline(
        self, origin: str
    ) -> None:
        """The admission half.

        A gate that starts refusing everything passes the refusal test above
        while silently reporting ``unknown`` for the whole catalog, and nothing
        in a refusal assertion notices that.
        """
        assert (
            compute_source_freshness(
                NOW - timedelta(days=800), "annually", NOW, origin=origin
            )
            == OVERDUE
        )

    def test_a_null_origin_still_reports_a_deadline(self) -> None:
        """NULL is a VRT, and ADR-002 Decision 5a projects its generation
        timestamp into last_refreshed_at precisely so freshness renders
        uniformly across record types. Gating it out would defeat that.
        """
        assert (
            compute_source_freshness(
                NOW - timedelta(days=800), "annually", NOW, origin=None
            )
            == OVERDUE
        )

    def test_an_unclassified_origin_withholds_advice_rather_than_inventing_it(
        self,
    ) -> None:
        """The allowlist's direction, pinned.

        A kind added to ORIGIN_KINDS and forgotten here reads ``unknown``. The
        partition test below is what makes that a loud failure rather than the
        permanent state, but the safe default matters on its own: the opposite
        default would announce a deadline for something that may not be
        refreshable at all.
        """
        assert (
            compute_source_freshness(
                NOW - timedelta(days=800), "annually", NOW, origin="warehouse"
            )
            == UNKNOWN
        )

    def test_the_origin_partition_covers_every_kind_that_exists(self) -> None:
        assert REFRESHABLE_ORIGINS | NON_REFRESHABLE_ORIGINS == set(ORIGIN_KINDS), (
            "REFRESHABLE_ORIGINS and NON_REFRESHABLE_ORIGINS no longer partition "
            "dataset_origin.ORIGIN_KINDS. A new origin kind needs a decision "
            "recorded in one of the two sets — leaving it out means it silently "
            "reports 'unknown' forever."
        )
        assert not REFRESHABLE_ORIGINS & NON_REFRESHABLE_ORIGINS


class TestVocabularyStaysInStepWithTheSchema:
    """The loud half: a new CHECK value must not default to ``unknown``."""

    def test_vocabulary_matches_the_records_check_constraint(self) -> None:
        constraint = next(
            c
            for c in Record.__table__.constraints
            if c.name == "chk_records_update_frequency"
        )
        stored = set(re.findall(r"'([^']+)'", str(constraint.sqltext)))
        assert stored, "failed to parse the CHECK constraint; fix this test first"
        assert stored == set(UPDATE_FREQUENCY_VOCABULARY), (
            "chk_records_update_frequency and UPDATE_FREQUENCY_VOCABULARY have "
            "drifted. Every accepted frequency needs either a period in "
            "FREQUENCY_PERIOD_DAYS or a deliberate place among the "
            "unscheduled values."
        )

    def test_every_vocabulary_value_is_either_timed_or_unscheduled(self) -> None:
        timed = set(FREQUENCY_PERIOD_DAYS)
        assert timed | UNSCHEDULED_FREQUENCIES == set(UPDATE_FREQUENCY_VOCABULARY)
        assert not timed & UNSCHEDULED_FREQUENCIES
        assert UNSCHEDULED_FREQUENCIES == set(_UNSCHEDULED)

    def test_periods_are_ordered_by_cadence(self) -> None:
        """A transposed pair in the table would otherwise be invisible."""
        by_cadence = [
            "continual",
            "daily",
            "weekly",
            "monthly",
            "quarterly",
            "biannually",
            "annually",
        ]
        periods = [FREQUENCY_PERIOD_DAYS[name] for name in by_cadence]
        assert periods == sorted(periods)
        assert set(by_cadence) == set(FREQUENCY_PERIOD_DAYS)


class TestNothingIsPersisted:
    """ADR-002 Decision 2: derived state gets no column and no write path."""

    def test_freshness_is_not_a_column_on_either_table(self) -> None:
        assert "source_freshness" not in Dataset.__table__.columns
        assert "source_freshness" not in Record.__table__.columns

    def test_freshness_is_not_accepted_by_the_metadata_patch(self) -> None:
        assert "source_freshness" not in DatasetMeta.model_fields

    async def test_patch_cannot_set_freshness_but_moves_what_it_derives_from(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """Refusal and admission in one request.

        ``update_frequency`` IS in the PATCH allowlist and freshness is
        computed from it, so this pins the whole shape at once: the body's
        ``freshness`` is ignored, and the value that comes back is the one the
        newly-PATCHed cadence implies rather than either the body's or the
        pre-PATCH answer.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Patch Freshness"
        )
        ds.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=400)
        ds.record.update_frequency = "asNeeded"
        await test_db_session.commit()

        before = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert before.json()["source_freshness"] == UNKNOWN

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"source_freshness": FRESH, "update_frequency": "annually"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["update_frequency"] == "annually"
        assert resp.json()["source_freshness"] == DUE

        after = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert after.status_code == 200
        assert after.json()["source_freshness"] == DUE


class TestResponseExposure:
    """Both surfaces serve it, and they serve the same answer."""

    @pytest.mark.parametrize(
        ("age_days", "frequency", "expected"),
        [
            (2, "annually", FRESH),
            (400, "annually", DUE),
            (800, "annually", OVERDUE),
            (800, "asNeeded", UNKNOWN),
        ],
    )
    async def test_dataset_and_ogc_record_agree(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        age_days: int,
        frequency: str,
        expected: str,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Freshness {frequency} {age_days}",
        )
        ds.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=age_days)
        ds.record.update_frequency = frequency
        await test_db_session.commit()

        detail = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert detail.status_code == 200
        assert detail.json()["source_freshness"] == expected

        record = await client.get(f"/collections/datasets/items/{ds.id}")
        assert record.status_code == 200
        props = record.json()["properties"]
        assert props["source_freshness"] == expected
        # The two columns it was computed from travel with it on this surface,
        # so a reader can check the arithmetic.
        assert props["update_frequency"] == frequency

    async def test_never_refreshed_dataset_reports_unknown_on_both(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Never Refreshed"
        )
        ds.last_refreshed_at = None
        ds.record.update_frequency = "daily"
        await test_db_session.commit()

        detail = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert detail.json()["source_freshness"] == UNKNOWN
        assert detail.json()["last_refreshed_at"] is None

        record = await client.get(f"/collections/datasets/items/{ds.id}")
        assert record.json()["properties"]["source_freshness"] == UNKNOWN

    async def test_a_created_dataset_reports_unknown_on_both_surfaces(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """The origin gate, end to end, on the case that motivated it.

        Identical inputs to the ``overdue`` row above apart from
        ``source_format``, so this pins the gate rather than some other reason
        the answer might be ``unknown``. The ``origin`` assertion is what makes
        that claim honest: without it, a fixture that failed to produce a
        ``created`` dataset would pass this test for the wrong reason.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Sketch Layer",
            source_format="created",
        )
        ds.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=800)
        ds.record.update_frequency = "annually"
        await test_db_session.commit()

        detail = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert detail.status_code == 200
        body = detail.json()
        assert body["origin"] == "created", "fixture did not produce a created origin"
        assert body["source_freshness"] == UNKNOWN
        # The timestamp is still served; only the verdict is withheld.
        assert body["last_refreshed_at"] is not None

        record = await client.get(f"/collections/datasets/items/{ds.id}")
        assert record.status_code == 200
        assert record.json()["properties"]["source_freshness"] == UNKNOWN

    async def test_the_search_listing_carries_it_through_its_response_model(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """The listing is the surface the catalog cards read, and it filters.

        ``/collections/datasets/items/{id}`` returns a raw ``JSONResponse``, so
        a key arriving there says nothing about ``/search/datasets/``, which
        serializes through ``OGCFeatureCollectionResponse`` and drops any
        property ``OGCRecordProperties`` does not declare.

        Filtered to a unique ``source_organization`` rather than reading the
        first row: the per-worker database accumulates datasets from every
        earlier test, so an unfiltered listing is a claim about the whole
        worker.
        """
        org = f"Freshness Listing Org {uuid.uuid4().hex[:8]}"
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Freshness In Listing",
            visibility="public",
        )
        ds.last_refreshed_at = datetime.now(timezone.utc) - timedelta(days=800)
        ds.record.update_frequency = "annually"
        ds.record.source_organization = org
        await test_db_session.commit()

        resp = await client.get(
            "/search/datasets/",
            params={"source_organization": org},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["features"]
        assert len(features) == 1, (
            f"expected exactly the seeded dataset, got {features}"
        )
        assert features[0]["id"] == str(ds.id)
        assert features[0]["properties"]["source_freshness"] == OVERDUE

    def test_both_response_schemas_declare_the_field(self) -> None:
        """Held separately from the wire assertions above.

        A dict key that no model declares would still serialize on the OGC
        surface, so the schema is what makes the field appear in OpenAPI and
        therefore in the SDKs.
        """
        from app.modules.catalog.datasets.domain.schemas import DatasetResponse

        assert "source_freshness" in DatasetResponse.model_fields
        assert "source_freshness" in OGCRecordProperties.model_fields

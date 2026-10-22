"""The ArcGIS item link on a dataset origin: validation, carry-forward and
who may read it."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.platform.dataset_origin import (
    build_origin_ref,
    carried_portal_link,
    set_dataset_origin,
)
from app.platform.jobs.models import IngestJob
from app.processing.ingest.schemas import FanOutLayerResult
from app.platform.portal_link import (
    registrable_domain,
    resolve_portal_link,
    same_registrable_domain,
)
from tests.factories import create_dataset, get_user_id

_ITEM = "0123456789abcdef0123456789abcdef"
_SERVICE = "https://services7.arcgis.com/abc/arcgis/rest/services/Water/FeatureServer"
_PORTAL = "https://myorg.maps.arcgis.com"


class TestResolvePortalLink:
    def test_a_matching_https_portal_is_kept(self) -> None:
        link = resolve_portal_link(_ITEM.upper(), _PORTAL + "/?x=1#top", _SERVICE)
        assert link.fields == {"item_id": _ITEM, "portal_url": _PORTAL}
        assert link.losses == []

    @pytest.mark.parametrize(
        ("given", "stored"),
        [
            ("https://myorg.maps.arcgis.com/sharing/rest", _PORTAL),
            ("https://myorg.maps.arcgis.com/sharing/rest/", _PORTAL),
            ("https://myorg.maps.arcgis.com/SHARING", _PORTAL),
            (
                "https://gis.example.org/portal/sharing/rest?f=json",
                "https://gis.example.org/portal",
            ),
            (
                "https://gis.example.org/portal/sharing",
                "https://gis.example.org/portal",
            ),
            (
                "https://gis.example.org/portal/sharingx",
                "https://gis.example.org/portal/sharingx",
            ),
        ],
    )
    def test_the_rest_endpoint_is_stored_as_the_portal_base(
        self, given: str, stored: str
    ) -> None:
        link = resolve_portal_link(_ITEM, given)
        assert link.fields["portal_url"] == stored

    @pytest.mark.parametrize(
        "portal_url",
        [
            "http://myorg.maps.arcgis.com",
            "javascript:alert(1)",
            "https://user:pw@myorg.maps.arcgis.com",
            "https:///nohost",
            "https://myorg.maps.arcgis.com:notaport",
            "https://myorg.maps.arcgis.com/" + "a" * 2100,
        ],
    )
    def test_a_malformed_or_insecure_portal_is_dropped(self, portal_url: str) -> None:
        link = resolve_portal_link(_ITEM, portal_url, _SERVICE)
        assert "portal_url" not in link.fields
        assert link.losses == ["portal_url_invalid"]
        assert link.fields == {"item_id": _ITEM}

    @pytest.mark.parametrize(
        "portal_url",
        [
            "https://evil.com\\.arcgis.com",
            "https://evil.com\\.maps.arcgis.com/portal",
            "https://evil.com\\@myorg.maps.arcgis.com",
            "https://evil.com%5C.arcgis.com",
            "https://evil.com\t.arcgis.com",
            "https://my org.arcgis.com",
            "https://my^org.arcgis.com",
            "https://myorg.maps.arcgis.com/a b",
            "https://evil.com/\\..",
        ],
    )
    def test_a_host_a_browser_would_read_differently_is_refused(
        self, portal_url: str
    ) -> None:
        link = resolve_portal_link(_ITEM, portal_url, _SERVICE)
        assert "portal_url" not in link.fields
        assert link.losses == ["portal_url_invalid"]

    def test_a_unicode_service_host_matches_a_unicode_portal_on_its_domain(
        self,
    ) -> None:
        link = resolve_portal_link(
            None, "https://münich.example/portal", "https://gis.münich.example/s"
        )
        assert link.fields == {"portal_url": "https://xn--mnich-kva.example/portal"}
        assert link.losses == []

    @pytest.mark.parametrize(
        ("service", "portal", "stored_host", "lookalike"),
        [
            ("gis.faß.de", "portal.faß.de", "portal.xn--fa-hia.de", "portal.fass.de"),
            (
                "gis.ςα.example",
                "portal.ςα.example",
                "portal.xn--mxa7a.example",
                "portal.σα.example",
            ),
        ],
        ids=["sharp_s", "final_sigma"],
    )
    def test_a_deviation_character_is_compared_as_a_browser_resolves_it(
        self, service: str, portal: str, stored_host: str, lookalike: str
    ) -> None:
        service_url = f"https://{service}/arcgis/rest/services/S"
        kept = resolve_portal_link(None, f"https://{portal}/portal", service_url)
        assert kept.fields == {"portal_url": f"https://{stored_host}/portal"}
        other = resolve_portal_link(None, f"https://{lookalike}", service_url)
        assert other.losses == ["portal_url_domain_mismatch"]
        assert same_registrable_domain(service_url, f"https://{portal}")
        assert not same_registrable_domain(service_url, f"https://{lookalike}")

    def test_a_joiner_outside_its_context_fails_closed(self) -> None:
        url = "https://a\u200db.example/s"
        assert not same_registrable_domain(url, url)
        assert resolve_portal_link(None, url, url).losses == ["portal_url_invalid"]

    def test_a_unicode_service_host_still_rejects_a_lookalike_portal(self) -> None:
        for portal in ("https://munich.example", "https://münich.evil.example"):
            link = resolve_portal_link(None, portal, "https://gis.münich.example/s")
            assert link.losses == ["portal_url_domain_mismatch"], portal

    @pytest.mark.parametrize(
        "service_url",
        [
            "https://" + "a" * 70 + ".example/s",
            "https://x\u2100.example/s",
            "https:///s",
        ],
    )
    def test_a_service_host_that_fails_idna_never_matches(
        self, service_url: str
    ) -> None:
        link = resolve_portal_link(None, "https://portal.example", service_url)
        assert link.losses == ["portal_url_domain_mismatch"]
        assert not same_registrable_domain(service_url, "https://portal.example")

    def test_a_unicode_host_is_compared_in_its_ascii_form(self) -> None:
        link = resolve_portal_link(None, "https://аrcgis.com", _SERVICE)
        assert link.losses == ["portal_url_domain_mismatch"]

    @pytest.mark.parametrize(
        "portal_url",
        [
            "https://evil.example.com",
            "https://arcgis.com.evil.example.com",
            "https://notarcgis.com",
        ],
    )
    def test_a_portal_on_another_domain_is_dropped(self, portal_url: str) -> None:
        link = resolve_portal_link(_ITEM, portal_url, _SERVICE)
        assert "portal_url" not in link.fields
        assert link.losses == ["portal_url_domain_mismatch"]

    def test_sibling_sites_under_a_country_suffix_do_not_match(self) -> None:
        link = resolve_portal_link(
            None, "https://a.co.uk/portal", "https://b.co.uk/server/rest/services/S"
        )
        assert link.losses == ["portal_url_domain_mismatch"]
        same = resolve_portal_link(
            None, "https://gis.org.co.uk/portal/", "https://maps.org.co.uk/arcgis/S"
        )
        assert same.fields == {"portal_url": "https://gis.org.co.uk/portal"}

    def test_ip_hosts_match_only_themselves(self) -> None:
        assert registrable_domain("10.1.2.3") == "10.1.2.3"
        link = resolve_portal_link(None, "https://10.1.2.4", "https://10.1.2.3/s")
        assert link.losses == ["portal_url_domain_mismatch"]

    def test_a_file_import_has_no_service_host_to_compare(self) -> None:
        link = resolve_portal_link(_ITEM, "https://portal.example.org/portal")
        assert link.fields["portal_url"] == "https://portal.example.org/portal"

    @pytest.mark.parametrize("item_id", ["short", "g" * 32, _ITEM + "0", ""])
    def test_a_bad_item_id_is_dropped_and_the_portal_kept(self, item_id: str) -> None:
        link = resolve_portal_link(item_id, _PORTAL, _SERVICE)
        assert link.fields == {"portal_url": _PORTAL}
        assert link.losses == ["item_id_invalid"]


class TestOriginAllowlist:
    @pytest.mark.parametrize("kind", ["service", "upload"])
    def test_service_and_upload_origins_carry_the_link(self, kind: str) -> None:
        ref = build_origin_ref(kind, item_id=_ITEM, portal_url=_PORTAL)
        assert ref["item_id"] == _ITEM and ref["portal_url"] == _PORTAL

    def test_a_postgis_origin_still_refuses_it(self) -> None:
        with pytest.raises(ValueError):
            build_origin_ref("postgis", table_name="a.b", item_id=_ITEM)


def _dataset(origin_ref: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        origin_ref=origin_ref,
        origin_uri=None,
        source_health="healthy",
        source_health_detail=None,
        last_checked_at=None,
    )


_LINKED_SERVICE = {
    "kind": "service",
    "service_type": "arcgis_featureserver",
    "url": _SERVICE,
    "item_id": _ITEM,
    "portal_url": _PORTAL,
}


class TestLinkSurvivesRestamps:
    def test_a_service_refresh_keeps_it(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        set_dataset_origin(
            dataset,
            "service",
            uri=_SERVICE,
            service_type="arcgis_featureserver",
            url=_SERVICE,
            layer_id="0",
        )
        assert dataset.origin_ref["item_id"] == _ITEM
        assert dataset.origin_ref["portal_url"] == _PORTAL

    def test_a_file_replace_of_a_service_dataset_keeps_it(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        set_dataset_origin(dataset, "upload", filename="a.gpkg", file_hash="h")
        assert dataset.origin_ref["kind"] == "upload"
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_restore_of_a_file_dataset_keeps_it(self) -> None:
        dataset = _dataset({"kind": "upload", "filename": "b.gpkg", "item_id": _ITEM})
        set_dataset_origin(dataset, "upload", filename="a.gpkg", file_hash="h")
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_new_link_replaces_the_old_one(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        other = "f" * 32
        set_dataset_origin(dataset, "upload", filename="a", item_id=other)
        assert dataset.origin_ref["item_id"] == other
        assert "portal_url" not in dataset.origin_ref

    def test_a_service_moved_to_another_domain_drops_the_link_and_says_so(
        self,
    ) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        losses = set_dataset_origin(
            dataset,
            "service",
            uri="https://gis.other.org/rest/FeatureServer",
            service_type="arcgis_featureserver",
            url="https://gis.other.org/rest/FeatureServer",
            layer_id="0",
        )
        assert losses == ["portal_url_domain_mismatch"]
        assert "item_id" not in dataset.origin_ref
        assert "portal_url" not in dataset.origin_ref

    def test_an_item_id_alone_is_dropped_when_the_service_moves_domain(self) -> None:
        old = {k: v for k, v in _LINKED_SERVICE.items() if k != "portal_url"}
        dataset = _dataset(old)
        losses = set_dataset_origin(
            dataset,
            "service",
            service_type="arcgis_featureserver",
            url="https://gis.other.org/rest/FeatureServer",
        )
        assert losses == ["portal_url_domain_mismatch"]
        assert "item_id" not in dataset.origin_ref

    def test_an_item_id_alone_survives_a_move_within_the_domain(self) -> None:
        old = {k: v for k, v in _LINKED_SERVICE.items() if k != "portal_url"}
        dataset = _dataset(old)
        assert (
            set_dataset_origin(
                dataset,
                "service",
                service_type="arcgis_featureserver",
                url="https://services8.arcgis.com/z/FeatureServer",
            )
            == []
        )
        assert dataset.origin_ref["item_id"] == _ITEM

    def test_a_rebind_to_a_non_arcgis_service_drops_the_link(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        losses = set_dataset_origin(
            dataset,
            "service",
            service_type="wfs",
            url="https://services7.arcgis.com/wfs",
            layer_id="roads",
        )
        assert losses == ["origin_link_unsupported"]
        assert "item_id" not in dataset.origin_ref
        assert "portal_url" not in dataset.origin_ref

    def test_a_service_restamp_on_the_same_domain_keeps_it(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        losses = set_dataset_origin(
            dataset,
            "service",
            url="https://services8.arcgis.com/z/FeatureServer",
            service_type="arcgis_featureserver",
        )
        assert losses == []
        assert dataset.origin_ref["portal_url"] == _PORTAL

    def test_an_upload_turned_into_a_service_is_checked_against_the_new_host(
        self,
    ) -> None:
        dataset = _dataset(
            {
                "kind": "upload",
                "filename": "a",
                "item_id": _ITEM,
                "portal_url": "https://evil.example",
            }
        )
        losses = set_dataset_origin(
            dataset,
            "service",
            url="https://gis.city.gov/server/rest/services/S/FeatureServer",
            service_type="arcgis_featureserver",
        )
        assert losses == ["portal_url_domain_mismatch"]
        assert dataset.origin_ref.get("portal_url") is None
        assert dataset.origin_ref.get("item_id") is None

    def test_a_service_turned_into_an_upload_keeps_the_link(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        assert set_dataset_origin(dataset, "upload", filename="a") == []
        assert dataset.origin_ref["portal_url"] == _PORTAL

    def test_a_stac_item_id_is_not_a_portal_item(self) -> None:
        stac = {"kind": "stac", "item_id": "S2A_2024", "url": "https://c.test"}
        assert carried_portal_link(stac) == {}
        dataset = _dataset(stac)
        set_dataset_origin(dataset, "upload", filename="a.tif")
        assert "item_id" not in dataset.origin_ref

    def test_other_kinds_never_gain_it(self) -> None:
        dataset = _dataset(dict(_LINKED_SERVICE))
        set_dataset_origin(dataset, "postgis", table_name="data.t")
        assert dataset.origin_ref == {"kind": "postgis", "table_name": "data.t"}


_PREVIEW = {
    "srid": 4326,
    "geometry_type": "Point",
    "layer_name": "0",
    "feature_count": 1,
    "columns": [],
    "sample_rows": [],
}


async def _job(session, job_id: str) -> IngestJob:
    import uuid

    await session.rollback()
    return (
        await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
    ).scalar_one()


class TestServicePreview:
    async def _preview(self, client, headers, **link):
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.catalog.sources.router.fetch_arcgis_layer_preview",
                AsyncMock(return_value=dict(_PREVIEW)),
            ),
        ):
            return await client.post(
                "/services/preview/",
                json={
                    "url": _SERVICE,
                    "service_type": "ArcGIS FeatureServer",
                    "layer_name": "Water",
                    "layer_id": 0,
                    **link,
                },
                headers=headers,
            )

    async def test_a_valid_link_is_stored_on_the_job(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        resp = await self._preview(
            client, admin_auth_header, item_id=_ITEM, portal_url=_PORTAL
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["origin_link_loss"] == []
        job = await _job(test_db_session, resp.json()["job_id"])
        assert job.user_metadata["item_id"] == _ITEM
        assert job.user_metadata["portal_url"] == _PORTAL

    async def test_a_foreign_portal_drops_the_link_and_reports_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        resp = await self._preview(
            client,
            admin_auth_header,
            item_id=_ITEM,
            portal_url="https://evil.example.com",
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["origin_link_loss"] == ["portal_url_domain_mismatch"]
        job = await _job(test_db_session, resp.json()["job_id"])
        assert "portal_url" not in job.user_metadata
        assert job.user_metadata["item_id"] == _ITEM

    async def test_a_non_arcgis_service_drops_the_link_and_says_so(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        with (
            patch(
                "app.modules.catalog.sources.router.validate_url_for_ssrf",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.catalog.sources.router.run_service_preview",
                AsyncMock(return_value=dict(_PREVIEW)),
            ),
            patch(
                "app.modules.catalog.sources.router.build_gdal_source",
                return_value=("WFS:https://x.test/wfs", "roads"),
            ),
        ):
            resp = await client.post(
                "/services/preview/",
                json={
                    "url": "https://x.test/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "roads",
                    "item_id": _ITEM,
                    "portal_url": _PORTAL,
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["origin_link_loss"] == ["origin_link_unsupported"]
        job = await _job(test_db_session, resp.json()["job_id"])
        assert "item_id" not in job.user_metadata

    @pytest.mark.parametrize(
        "body",
        [{"item_id": "a" * 65}, {"portal_url": "https://x.test/" + "a" * 2100}],
    )
    async def test_an_out_of_bounds_value_is_refused_not_dropped(
        self, client: AsyncClient, admin_auth_header: dict, body: dict
    ) -> None:
        resp = await self._preview(client, admin_auth_header, **body)
        assert resp.status_code == 422

    async def test_no_link_means_nothing_stored(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        resp = await self._preview(client, admin_auth_header)
        assert resp.json()["origin_link_loss"] == []
        job = await _job(test_db_session, resp.json()["job_id"])
        assert "item_id" not in job.user_metadata


class TestFileCommit:
    async def _pending(self, session) -> IngestJob:
        job = IngestJob(
            source_filename="t.gpkg",
            file_path="/tmp/fake-link.gpkg",
            status="pending",
            created_by=await get_user_id(session, "admin"),
            user_metadata={"file_type": "vector"},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def test_the_link_reaches_the_job_and_a_bad_one_is_reported(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        job = await self._pending(test_db_session)
        with patch(
            "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
        ):
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={
                    "title": "T",
                    "item_id": _ITEM,
                    "portal_url": "http://insecure.example.com",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 202, resp.text
        assert resp.json()["origin_link_loss"] == ["portal_url_invalid"]
        stored = await _job(test_db_session, str(job.id))
        assert stored.user_metadata["item_id"] == _ITEM
        assert "portal_url" not in stored.user_metadata

    @pytest.mark.parametrize("file_type", ["service", "raster"])
    async def test_an_import_that_stores_no_link_reports_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, file_type
    ) -> None:
        job = IngestJob(
            source_filename="t",
            status="pending",
            created_by=await get_user_id(test_db_session, "admin"),
            **(
                {"source_url": "https://x.test/FeatureServer"}
                if file_type == "service"
                else {"file_path": "/tmp/fake-link.tif"}
            ),
            user_metadata={} if file_type == "service" else {"file_type": "raster"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        with (
            patch(
                "app.processing.ingest.router.queue_ingest_job",
                new_callable=AsyncMock,
            ),
            patch("app.platform.security.validate_url_for_ssrf", AsyncMock()),
        ):
            resp = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "T", "item_id": _ITEM},
                headers=admin_auth_header,
            )
        assert resp.status_code == 202, resp.text
        assert resp.json()["origin_link_loss"] == ["origin_link_unsupported"]
        stored = await _job(test_db_session, str(job.id))
        assert "item_id" not in stored.user_metadata

    async def test_fan_out_children_inherit_the_link(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        job = await self._pending(test_db_session)
        job.user_metadata = {"file_type": "vector", "all_layers": ["a"]}
        await test_db_session.commit()
        seen: dict = {}

        async def spawn(parent, layer, db):
            seen.update(parent.user_metadata)
            return FanOutLayerResult(layer_name="a", status="queued")

        with patch("app.processing.ingest.router.create_fan_out_jobs", spawn):
            resp = await client.post(
                f"/ingest/commit-fan-out/{job.id}",
                json={
                    "layers": [{"layer_name": "a"}],
                    "item_id": _ITEM,
                    "portal_url": "https://portal.example.org/portal",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 202, resp.text
        assert seen["item_id"] == _ITEM
        assert seen["portal_url"] == "https://portal.example.org/portal"

    async def test_a_retry_without_the_link_clears_the_one_a_failed_dispatch_left(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        job = await self._pending(test_db_session)
        job.user_metadata = {"file_type": "vector", "all_layers": ["a"]}
        await test_db_session.commit()
        outcomes = iter(["failed", "queued"])
        seen: list[dict] = []

        async def spawn(parent, layer, db):
            seen.append(dict(parent.user_metadata))
            status = next(outcomes)
            return FanOutLayerResult(
                layer_name="a",
                status=status,
                error="boom" if status == "failed" else None,
            )

        body = {"layers": [{"layer_name": "a"}]}
        with patch("app.processing.ingest.router.create_fan_out_jobs", spawn):
            first = await client.post(
                f"/ingest/commit-fan-out/{job.id}",
                json={**body, "item_id": _ITEM, "portal_url": "https://p.example.org"},
                headers=admin_auth_header,
            )
            retry = await client.post(
                f"/ingest/commit-fan-out/{job.id}", json=body, headers=admin_auth_header
            )
        assert first.status_code == retry.status_code == 202
        assert seen[0]["item_id"] == _ITEM
        assert "item_id" not in seen[1] and "portal_url" not in seen[1]
        stored = await _job(test_db_session, str(job.id))
        assert "item_id" not in stored.user_metadata
        assert "portal_url" not in stored.user_metadata


class TestProvenanceProjection:
    async def _dataset(self, session, owner_id):
        dataset = await create_dataset(
            session,
            created_by=owner_id,
            name="Linked item",
            visibility="public",
            source_format="arcgis_featureserver",
        )
        dataset.origin_ref = dict(_LINKED_SERVICE)
        await session.commit()
        return dataset

    async def test_owner_and_admin_see_the_link(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ) -> None:
        me = await client.get("/auth/me/", headers=viewer_auth_header)
        import uuid

        ds = await self._dataset(test_db_session, uuid.UUID(me.json()["id"]))
        for headers in (viewer_auth_header, admin_auth_header):
            body = (await client.get(f"/datasets/{ds.id}", headers=headers)).json()
            assert body["origin_ref"]["item_id"] == _ITEM
            assert body["origin_ref"]["portal_url"] == _PORTAL

    async def test_a_non_owner_and_an_anonymous_reader_do_not(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ) -> None:
        ds = await self._dataset(
            test_db_session, await get_user_id(test_db_session, "admin")
        )
        for headers in (viewer_auth_header, {}):
            resp = await client.get(f"/datasets/{ds.id}", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["origin_ref"] is None
            assert _ITEM not in resp.text

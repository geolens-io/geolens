"""The raster probe child: bounded, and silent about what it read.

A CRS in a raster file can make PROJ open a path and block, holding the GIL,
so a timeout in the calling thread would never fire. The reads run in a
child the parent kills at a deadline. These tests replace the child with a
stand-in that stalls or fails loudly, and check that each caller refuses on
time with our own text and nothing the child printed. No test here builds a
CRS that points anywhere: the stall is a plain sleep.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import numpy as np
import pytest
import rasterio
import structlog
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from sqlalchemy import select

from app.core.geo import wkt_has_degree_unit, wkt_is_geographic, wkt_metres_per_unit
from app.platform.jobs.models import IngestJob
from app.processing.raster import probe
from app.processing.raster.cog import (
    _predictor_supported,
    check_cog_compliance,
    extract_raster_metadata,
)
from app.processing.raster.quicklook import generate_quicklook

pytestmark = pytest.mark.anyio

# What a stand-in child prints and where it leaves traces, none of which may
# reach a response, a stored reason or an exception message.
_CHILD_TEXT = "/app/staging/9f2c_secret.tif TIFFReadDirectory: child-only text"


def _stand_in(monkeypatch, script: str) -> None:
    """Replace the probe child with ``python -c <script>``."""
    monkeypatch.setattr(
        probe, "_command", lambda *_args: [sys.executable, "-c", script]
    )


def _stalling_child(monkeypatch, tmp_path, *, seconds: float = 8.0) -> str:
    pid_file = tmp_path / "child.pid"
    _stand_in(
        monkeypatch,
        "import os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"print({_CHILD_TEXT!r}, flush=True)\n"
        f"sys.stderr.write({_CHILD_TEXT!r}); sys.stderr.flush()\n"
        f"time.sleep({seconds})\n",
    )
    return str(pid_file)


def _failing_child(monkeypatch, *, stdout: str, code: int = 1) -> None:
    _stand_in(
        monkeypatch,
        "import sys\n"
        f"sys.stderr.write({_CHILD_TEXT!r})\n"
        f"print({stdout!r})\n"
        f"sys.exit({code})\n",
    )


def _geotiff(path, *, epsg: int, bounds, width: int = 64, height: int = 64) -> str:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs=CRS.from_epsg(epsg),
        transform=from_bounds(*bounds, width, height),
        nodata=-9999.0,
    ) as dst:
        rng = np.random.default_rng(2288)
        dst.write(rng.random((1, height, width), dtype="float32"))
    return str(path)


class TestTheParentBoundsTheChild:
    def test_a_stalled_child_is_killed_at_the_deadline(
        self, monkeypatch, tmp_path
    ) -> None:
        pid_file = _stalling_child(monkeypatch, tmp_path)

        started = time.monotonic()
        with pytest.raises(probe.RasterProbeError) as exc_info:
            probe.read_raster_metadata("any.tif", timeout=1)
        elapsed = time.monotonic() - started

        assert elapsed < 5, f"the probe waited {elapsed:.1f}s past a 1s deadline"
        assert exc_info.value.kind == "timeout"
        assert str(exc_info.value) == (
            "Reading the raster took longer than 1 seconds, so it was stopped."
        )
        with pytest.raises(ProcessLookupError):
            os.kill(int(open(pid_file).read()), 0)

    @pytest.mark.parametrize(
        "stdout,code,kind",
        [
            (json.dumps({"error": "open", "message": _CHILD_TEXT}), 1, "open"),
            (json.dumps({"error": "invalid", "exception": "CRSError"}), 1, "read"),
            (json.dumps({"error": _CHILD_TEXT}), 1, "internal"),
            (_CHILD_TEXT, 0, "internal"),
            (json.dumps({"no": "result"}), 0, "internal"),
        ],
    )
    def test_a_failed_child_comes_back_as_a_kind_only(
        self, monkeypatch, tmp_path, stdout, code, kind
    ) -> None:
        _failing_child(monkeypatch, stdout=stdout, code=code)

        with pytest.raises(probe.RasterProbeError) as exc_info:
            probe.read_raster_metadata("any.tif")

        assert exc_info.value.kind == kind
        assert "secret" not in repr(exc_info.value)
        assert "child-only" not in str(exc_info.value)

    def test_the_child_runs_under_the_clamps_with_proj_offline(
        self, monkeypatch, tmp_path
    ) -> None:
        keys = ["PROJ_NETWORK", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS", "GDAL_HTTP_TIMEOUT"]
        _stand_in(
            monkeypatch,
            "import json, os\n"
            f"print(json.dumps({{'result': {{k: os.environ.get(k) for k in {keys!r}}}}}))\n",
        )

        env = probe.read_raster_metadata("any.tif")

        assert env["PROJ_NETWORK"] == "OFF"
        assert env["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] == "tif,tiff,vrt"
        assert env["GDAL_HTTP_TIMEOUT"] == "300"


class TestOperatorDiagnostics:
    """Job reasons stay generic; the operator log says which failure it was."""

    @pytest.mark.parametrize(
        "raised,category",
        [
            (rasterio.errors.RasterioIOError("not a raster"), "open"),
            (rasterio.errors.CRSError("no such CRS"), "invalid"),
            (ModuleNotFoundError("gone"), "internal"),
            (rasterio.errors.EnvError("bad config"), "internal"),
        ],
    )
    def test_the_child_tells_bad_raster_data_from_its_own_failures(
        self, monkeypatch, capsys, raised, category
    ) -> None:
        def _fail(_path):
            raise raised

        monkeypatch.setattr(probe, "_metadata", _fail)

        assert probe.main(["metadata", "any.tif"]) == 1
        reply = json.loads(capsys.readouterr().out)
        assert reply == {"error": category, "exception": type(raised).__name__}

    def test_operators_can_tell_a_startup_failure_from_bad_raster_data(
        self, monkeypatch
    ) -> None:
        def _logged(script: str) -> dict:
            _stand_in(monkeypatch, script)
            with structlog.testing.capture_logs() as captured:
                with pytest.raises(probe.RasterProbeError):
                    probe.read_raster_metadata("any.tif")
            events = [e for e in captured if e["event"] == "raster probe failed"]
            assert len(events) == 1, captured
            assert "not_a_module" not in repr(captured)
            assert "secret" not in repr(captured)
            return events[0]

        startup = _logged("import app.processing.raster.not_a_module")
        bad_data = _logged(
            "import json, sys\n"
            f"sys.stderr.write({_CHILD_TEXT!r})\n"
            "print(json.dumps({'error': 'invalid', 'exception': 'CRSError'}))\n"
            "sys.exit(1)\n"
        )
        killed = _logged("import os, signal; os.kill(os.getpid(), signal.SIGKILL)")

        assert startup["category"] == "no_reply"
        assert startup["exception"] == "ModuleNotFoundError"
        assert startup["returncode"] == 1
        assert (bad_data["category"], bad_data["exception"]) == ("invalid", "CRSError")
        assert (killed["category"], killed["signal"]) == ("killed", "SIGKILL")
        assert {startup["op"], bad_data["op"], killed["op"]} == {"metadata"}


class TestCallersRefuseOnTime:
    async def test_the_preview_answers_422_before_the_proxy_gives_up(
        self, client, admin_auth_header, test_db_session, monkeypatch, tmp_path
    ) -> None:
        from app.modules.auth.models import User

        source = _geotiff(tmp_path / "dem.tif", epsg=4326, bounds=(0, 0, 1, 1))
        admin = (
            await test_db_session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="dem.tif",
            file_path=source,
            created_by=admin.id,
            status="pending",
            user_metadata={"file_type": "raster"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        _stalling_child(monkeypatch, tmp_path)
        monkeypatch.setattr(probe, "PREVIEW_TIMEOUT_SECONDS", 1)

        started = time.monotonic()
        resp = await client.post(f"/ingest/preview/{job.id}", headers=admin_auth_header)
        elapsed = time.monotonic() - started

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "raster_preview_failed",
            "message": (
                "Reading the raster took longer than 1 seconds, so it was stopped."
            ),
        }
        assert elapsed < 5
        assert "secret" not in resp.text

    @pytest.mark.parametrize("child", ["stalls", "fails loudly"])
    async def test_ingest_fails_the_job_with_our_text_only(
        self, test_db_session, monkeypatch, tmp_path, child
    ) -> None:
        from app.modules.auth.models import User
        from app.processing.ingest.tasks_raster import ingest_raster

        source = _geotiff(tmp_path / "dem.tif", epsg=4326, bounds=(0, 0, 1, 1))
        admin = (
            await test_db_session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="dem.tif",
            file_path=source,
            created_by=admin.id,
            status="pending",
            user_metadata={"file_type": "raster"},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        if child == "stalls":
            _stalling_child(monkeypatch, tmp_path)
            monkeypatch.setattr(probe, "READ_TIMEOUT_SECONDS", 1)
            expected = (
                "Reading the raster took longer than 1 seconds, so it was stopped."
            )
        else:
            _failing_child(monkeypatch, stdout=json.dumps({"error": _CHILD_TEXT}))
            expected = "Reading the raster failed unexpectedly."

        started = time.monotonic()
        with pytest.raises(ValueError) as exc_info:
            await ingest_raster.func(
                job_id=str(job.id),
                file_path=source,
                user_id=str(admin.id),
                attempt_id=str(job.attempt_id),
            )
        assert time.monotonic() - started < 5
        assert str(exc_info.value) == expected

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.dataset_id is None
        assert "secret" not in (job.error_message or "")
        assert "child-only" not in (job.error_message or "")


_FIXTURES = [
    ("geographic", 4326, (10.0, 40.0, 11.0, 41.0)),
    ("utm", 32618, (500000.0, 4500000.0, 501920.0, 4501920.0)),
    ("us_feet", 2263, (980000.0, 190000.0, 990000.0, 200000.0)),
    ("antimeridian", 4326, (170.0, -10.0, 190.0, 10.0)),
]


class TestTheChildAnswersAsTheInProcessReadDid:
    @pytest.mark.parametrize("name,epsg,bounds", _FIXTURES)
    def test_inspection_matches_the_in_process_read(
        self, tmp_path, name, epsg, bounds
    ) -> None:
        path = _geotiff(tmp_path / f"{name}.tif", epsg=epsg, bounds=bounds)

        inspection = probe.inspect_raster(path, expected_compression="DEFLATE")

        assert inspection["metadata"] == json.loads(
            json.dumps(extract_raster_metadata(path))
        )
        assert (inspection["compliant"], inspection["compliance_reason"]) == (
            check_cog_compliance(path, expected_compression="DEFLATE")
        )
        assert inspection["predictor_supported"] is _predictor_supported(path)
        assert probe.read_raster_metadata(path) == inspection["metadata"]

    def test_quicklooks_match_the_in_process_render(self, tmp_path) -> None:
        path = _geotiff(tmp_path / "ql.tif", epsg=32618, bounds=_FIXTURES[1][2])

        for size in (256, 512):
            assert probe.render_quicklook(path, size) == generate_quicklook(path, size)

    @pytest.mark.parametrize("epsg", [4326, 32618, 2263, 4807])
    def test_crs_facts_match_the_wkt_helpers(self, epsg) -> None:
        wkt = CRS.from_epsg(epsg).to_wkt()

        assert probe.crs_facts(wkt) == {
            "is_geographic": wkt_is_geographic(wkt),
            "has_degree_unit": wkt_has_degree_unit(wkt),
            "metres_per_unit": wkt_metres_per_unit(wkt),
        }

    def test_an_unopenable_file_is_an_open_error(self, tmp_path) -> None:
        path = tmp_path / f"{uuid.uuid4().hex}.tif"
        path.write_bytes(b"II*\x00" + b"\x00" * 64)

        with pytest.raises(probe.RasterProbeError) as exc_info:
            probe.inspect_raster(str(path))

        assert exc_info.value.kind == "open"
        assert path.name not in str(exc_info.value)

"""The point cloud decode child: bounded, and silent about what it printed.

lazrs holds the GIL while it decodes, and a decode that never returned would
hold its thread for good, so the doors and the worker decode in a child the
parent kills at a deadline. These tests run the real child with lazrs made to
stall or crash, or replace it with a stand-in that prints freely, and check
that each caller refuses on time with our own text.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import os
import signal
import struct
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import lazrs
import numpy as np
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from structlog.testing import capture_logs

from app.core.config import settings
from app.core.upload_errors import UnsafeUploadError, refusal_detail
from app.platform.jobs.models import IngestJob
from app.platform.storage.local import LocalStorageProvider
from app.processing.ingest import pointcloud as pointcloud_module
from app.processing.ingest.pointcloud import (
    PointCloudDecodeError,
    PointCloudDecodeTimeout,
    inspect_pointcloud,
    staged_pointcloud_metadata,
)
from tests.pointcloud_files import copc

# What a stand-in child prints, none of which may reach a refusal, a response,
# a stored reason or the log.
_CHILD_TEXT = "/app/staging/5e1f_secret.copc.laz lazrs: child-only text"


def _write(tmp_path: Path, data: bytes) -> str:
    path = tmp_path / "cloud.copc.laz"
    path.write_bytes(data)
    return str(path)


def _stand_in(monkeypatch, script: str) -> None:
    """Replace the decode child with ``python -c <script> top|every <cpu> <path>``."""
    monkeypatch.setattr(
        pointcloud_module,
        "_decoder_command",
        lambda every, cpu_seconds, path: [
            sys.executable,
            "-c",
            script,
            "every" if every else "top",
            str(cpu_seconds),
            path,
        ],
    )


def _decoder_with(monkeypatch, patch: str) -> None:
    """The real decode child, run after ``patch`` has changed lazrs inside it."""
    _stand_in(
        monkeypatch,
        "import os, runpy, signal, time\n"
        "import lazrs\n"
        f"{patch}\n"
        "runpy.run_module('app.processing.ingest.pointcloud_decode', run_name='__main__')\n",
    )


def _stalled_decoder(monkeypatch, tmp_path: Path) -> Path:
    """The real decode child, whose lazrs decode never returns.

    Returns the file the child writes its pid to once the decode has started.
    """
    pid_file = tmp_path / "decoder.pid"
    _decoder_with(
        monkeypatch,
        "def _stall(*args):\n"
        f"    open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "    time.sleep(600)\n"
        "lazrs.decompress_points_with_chunk_table = _stall",
    )
    return pid_file


def _burning_decoder(monkeypatch) -> None:
    """The real decode child, whose lazrs decode spins on the CPU and never returns."""
    _decoder_with(
        monkeypatch,
        "def _burn(*args):\n"
        "    while True:\n"
        "        pass\n"
        "lazrs.decompress_points_with_chunk_table = _burn",
    )


def _assert_gone(pid_file: Path) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def _kill_once_decoding(pid_file: Path, signum: int) -> None:
    """Send ``signum`` from outside to a stalled decoder once its decode starts."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            os.kill(int(pid_file.read_text()), signum)
            return
        except (FileNotFoundError, ValueError):
            time.sleep(0.01)


class TestTheParentBoundsTheChild:
    def test_a_decode_that_blocks_is_stopped_at_the_deadline(
        self, monkeypatch, tmp_path
    ) -> None:
        """A child with CPU time to spare that the deadline stops says nothing about the file."""
        pid_file = _stalled_decoder(monkeypatch, tmp_path)
        monkeypatch.setattr(pointcloud_module, "TOP_NODE_DECODE_SECONDS", 2)

        started = time.monotonic()
        with pytest.raises(PointCloudDecodeTimeout) as stopped:
            inspect_pointcloud(_write(tmp_path, copc()))
        elapsed = time.monotonic() - started

        assert elapsed < 6, f"the door waited {elapsed:.1f}s past a 2s deadline"
        assert str(stopped.value) == (
            "Decoding the point cloud took longer than 2 seconds, so it was stopped."
        )
        _assert_gone(pid_file)

    def test_a_decode_that_spins_dies_of_its_cpu_limit(
        self, monkeypatch, tmp_path
    ) -> None:
        """A child that uses up its CPU time is refused before the deadline, as the file's fault."""
        _burning_decoder(monkeypatch)
        monkeypatch.setattr(pointcloud_module, "TOP_NODE_DECODE_SECONDS", 6)

        started = time.monotonic()
        with pytest.raises(UnsafeUploadError) as refusal:
            inspect_pointcloud(_write(tmp_path, copc()))
        elapsed = time.monotonic() - started

        assert elapsed < 6, f"the child spun {elapsed:.1f}s, past its 2s of CPU time"
        assert refusal_detail(refusal.value) == {
            "code": "pointcloud_invalid",
            "message": "The point cloud takes more than 2 seconds to decode.",
            "limit": 2,
        }

    def test_a_decode_that_crashes_the_child_is_refused_as_undecodable(
        self, monkeypatch, tmp_path
    ) -> None:
        _decoder_with(
            monkeypatch,
            "lazrs.decompress_points_with_chunk_table = "
            "lambda *args: os.kill(os.getpid(), signal.SIGSEGV)",
        )

        with capture_logs() as logs:
            with pytest.raises(UnsafeUploadError) as refusal:
                inspect_pointcloud(_write(tmp_path, copc()))

        assert (refusal.value.code, str(refusal.value)) == (
            "pointcloud_decode_failed",
            "The point cloud's points don't decode as its header describes.",
        )
        (failure,) = [e for e in logs if e["event"] == "Point cloud decode failed"]
        assert (failure["category"], failure["signal"]) == ("killed", "SIGSEGV")
        (refused,) = [e for e in logs if e["event"] == "Point cloud refused"]
        assert (refused["reason"], refused["event_type"]) == (
            "decode_crash",
            "security",
        )

    @pytest.mark.parametrize(
        "name", ["SIGSEGV", "SIGBUS", "SIGABRT", "SIGILL", "SIGFPE"]
    )
    def test_a_crash_signal_is_refused_as_undecodable(
        self, monkeypatch, tmp_path, name
    ) -> None:
        _stand_in(
            monkeypatch, f"import os, signal\nos.kill(os.getpid(), signal.{name})\n"
        )

        with pytest.raises(UnsafeUploadError) as refusal:
            inspect_pointcloud(_write(tmp_path, copc()))

        assert refusal.value.code == "pointcloud_decode_failed"

    @pytest.mark.parametrize("name", ["SIGKILL", "SIGTERM", "SIGUSR1"])
    def test_any_other_signal_says_nothing_about_the_file(
        self, monkeypatch, tmp_path, name
    ) -> None:
        _stand_in(
            monkeypatch, f"import os, signal\nos.kill(os.getpid(), signal.{name})\n"
        )

        with pytest.raises(PointCloudDecodeError):
            inspect_pointcloud(_write(tmp_path, copc()))

    def test_the_child_decodes_with_path_alone(self, monkeypatch, tmp_path) -> None:
        """The child sees no setting and no secret, and still answers."""
        envs: list[dict[str, str]] = []
        run = pointcloud_module.run_child

        def _run(argv, **kwargs):
            envs.append(kwargs["env"])
            return run(argv, **kwargs)

        monkeypatch.setattr(pointcloud_module, "run_child", _run)

        assert inspect_pointcloud(_write(tmp_path, copc())).point_count == 100
        # Names only, so a failure never prints a secret's value.
        assert [sorted(env) for env in envs] == [["PATH"]]
        assert envs[0]["PATH"] == os.environ["PATH"]


@pytest.mark.parametrize(
    ("reply", "raised"),
    [
        pytest.param(f"print({_CHILD_TEXT!r})", PointCloudDecodeError, id="text"),
        pytest.param(
            f"print(json.dumps({{'result': {{'refused': {_CHILD_TEXT!r}}}}}))",
            PointCloudDecodeError,
            id="unknown-check",
        ),
        pytest.param(
            f"print(json.dumps({{'result': {{'low': {_CHILD_TEXT!r}, 'high': []}}}}))",
            PointCloudDecodeError,
            id="text-for-corners",
        ),
        pytest.param(
            "print(json.dumps({'result': {'low': [float('nan')] * 5, 'high': [0.0] * 5}}))",
            PointCloudDecodeError,
            id="nan-corners",
        ),
        pytest.param(
            f"print(json.dumps({{'error': {_CHILD_TEXT!r}}})); sys.exit(1)",
            PointCloudDecodeError,
            id="unknown-error",
        ),
        pytest.param(
            "print('[' * 1_000_000 + ']' * 1_000_000)",
            PointCloudDecodeError,
            id="nested-past-the-stack",
        ),
        pytest.param(
            "print(json.dumps({'result': {'refused': 'decode_voxel'}}))",
            UnsafeUploadError,
            id="named-check",
        ),
        pytest.param(
            f"print({_CHILD_TEXT!r}, flush=True); os.kill(os.getpid(), signal.SIGSEGV)",
            UnsafeUploadError,
            id="crashed",
        ),
        pytest.param(
            f"print({_CHILD_TEXT!r}, flush=True); os.kill(os.getpid(), signal.SIGKILL)",
            PointCloudDecodeError,
            id="killed",
        ),
    ],
)
def test_nothing_the_child_prints_reaches_the_refusal_or_the_log(
    monkeypatch, tmp_path, reply, raised
) -> None:
    _stand_in(
        monkeypatch,
        "import json, os, signal, sys\n"
        f"sys.stderr.write({_CHILD_TEXT!r} + '\\n'); sys.stderr.flush()\n"
        f"{reply}\n",
    )

    with capture_logs() as logs:
        with pytest.raises(raised) as exc_info:
            inspect_pointcloud(_write(tmp_path, copc()))

    seen = repr(exc_info.value) + json.dumps(refusal_detail(exc_info.value))
    seen += repr(logs)
    assert "secret" not in seen
    assert "child-only" not in seen


async def _pending_job(session, path: str) -> IngestJob:
    """A staged point cloud upload of the admin's, awaiting its preview."""
    from app.modules.auth.models import User

    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    job = IngestJob(
        source_filename="cloud.copc.laz",
        file_path=path,
        created_by=admin.id,
        status="pending",
        user_metadata={"file_type": "pointcloud"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def test_the_doors_answer_503_to_a_decode_the_server_stopped(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch, tmp_path
) -> None:
    """The preview and the upload door let the client retry, since the file isn't at fault."""
    path = _write(tmp_path, copc())
    job = await _pending_job(test_db_session, path)
    _stalled_decoder(monkeypatch, tmp_path)
    monkeypatch.setattr(pointcloud_module, "TOP_NODE_DECODE_SECONDS", 1)

    resp = await client.post(f"/ingest/preview/{job.id}", headers=admin_auth_header)
    with pytest.raises(HTTPException) as upload:
        await staged_pointcloud_metadata(path, "pointcloud")

    retry = "Checking the point cloud took too long. Try again."
    assert (resp.status_code, resp.json()["detail"]) == (503, retry)
    assert (upload.value.status_code, upload.value.detail) == (503, retry)


async def test_the_preview_answers_with_our_text_only(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch, tmp_path
) -> None:
    job = await _pending_job(test_db_session, _write(tmp_path, copc()))
    _stand_in(
        monkeypatch,
        "import json, sys\n"
        f"sys.stderr.write({_CHILD_TEXT!r} + '\\n'); sys.stderr.flush()\n"
        "print(json.dumps({'result': {'refused': 'decode_voxel'}}))\n",
    )

    resp = await client.post(f"/ingest/preview/{job.id}", headers=admin_auth_header)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == {
        "code": "pointcloud_invalid",
        "message": "A node's points lie outside its octree cell.",
    }
    assert "secret" not in resp.text


@pytest.mark.parametrize("child", ["stalls", "prints text"])
async def test_ingest_fails_the_job_with_our_text_only(
    test_db_session, monkeypatch, tmp_path, child
) -> None:
    from app.processing.ingest.tasks import ingest_pointcloud

    path = _write(tmp_path, copc())
    job = await _pending_job(test_db_session, path)
    if child == "stalls":
        _stalled_decoder(monkeypatch, tmp_path)
        monkeypatch.setattr(pointcloud_module, "DECODE_FLOOR_SECONDS", 1)
        raised = PointCloudDecodeTimeout
        expected = (
            "Decoding the point cloud took longer than 1 seconds, so it was stopped."
        )
    else:
        _stand_in(monkeypatch, f"print({_CHILD_TEXT!r})")
        raised = PointCloudDecodeError
        expected = "Decoding the point cloud failed unexpectedly."

    started = time.monotonic()
    with pytest.raises(raised):
        await ingest_pointcloud.func(
            job_id=str(job.id),
            file_path=path,
            user_id=str(job.created_by),
            attempt_id=str(job.attempt_id),
        )
    assert time.monotonic() - started < 6

    await test_db_session.refresh(job)
    assert (job.status, job.dataset_id, job.error_message, job.error_code) == (
        "failed",
        None,
        expected,
        None,
    )


async def _presigned_upload(monkeypatch, tmp_path):
    """A point cloud's presigned upload and its frozen copy, as the completion door sees them."""
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
    (tmp_path / "staging").mkdir()
    storage = LocalStorageProvider(base_dir=str(tmp_path / "store"))
    job = SimpleNamespace(
        id=uuid.uuid4(), user_metadata={"s3_key": "staging/job/cloud.copc.laz"}
    )
    frozen = "staging/job/frozen/cloud.copc.laz"
    for key in (job.user_metadata["s3_key"], frozen):
        await storage.put(key, copc())
    return storage, job, frozen


async def test_a_signal_from_outside_keeps_the_presigned_upload(
    monkeypatch, tmp_path
) -> None:
    """A SIGKILL the door didn't send, as from the OOM killer, is no verdict on the file."""
    from app.processing.ingest.presigned import admit_presigned_pointcloud

    storage, job, frozen = await _presigned_upload(monkeypatch, tmp_path)
    pid_file = _stalled_decoder(monkeypatch, tmp_path)
    killer = threading.Thread(
        target=_kill_once_decoding, args=(pid_file, signal.SIGKILL)
    )
    killer.start()
    try:
        with pytest.raises(PointCloudDecodeError):
            await admit_presigned_pointcloud(storage, job, frozen_key=frozen)
    finally:
        killer.join()

    assert await storage.exists(job.user_metadata["s3_key"])
    assert not await storage.exists(frozen)


async def test_a_decode_past_the_deadline_keeps_the_presigned_upload(
    monkeypatch, tmp_path
) -> None:
    """Running out of time is no verdict on the file, so the client can complete again."""
    from app.processing.ingest.presigned import admit_presigned_pointcloud

    storage, job, frozen = await _presigned_upload(monkeypatch, tmp_path)
    _stalled_decoder(monkeypatch, tmp_path)
    monkeypatch.setattr(pointcloud_module, "TOP_NODE_DECODE_SECONDS", 1)

    with pytest.raises(HTTPException) as failure:
        await admit_presigned_pointcloud(storage, job, frozen_key=frozen)

    assert (failure.value.status_code, failure.value.detail) == (
        503,
        "Checking the point cloud took too long. Try again.",
    )
    assert await storage.exists(job.user_metadata["s3_key"])
    assert not await storage.exists(frozen)


async def test_a_decode_that_spins_refuses_the_presigned_upload(
    monkeypatch, tmp_path
) -> None:
    """A child that uses up its CPU time refuses the file, and both objects go."""
    from app.processing.ingest.presigned import admit_presigned_pointcloud

    storage, job, frozen = await _presigned_upload(monkeypatch, tmp_path)
    _burning_decoder(monkeypatch)
    monkeypatch.setattr(pointcloud_module, "TOP_NODE_DECODE_SECONDS", 6)

    with pytest.raises(HTTPException) as refusal:
        await admit_presigned_pointcloud(storage, job, frozen_key=frozen)

    assert (refusal.value.status_code, refusal.value.detail) == (
        422,
        {
            "code": "pointcloud_invalid",
            "message": "The point cloud takes more than 2 seconds to decode.",
            "limit": 2,
        },
    )
    assert not await storage.exists(job.user_metadata["s3_key"])
    assert not await storage.exists(frozen)


async def test_a_decoder_crash_refuses_the_presigned_upload(
    monkeypatch, tmp_path
) -> None:
    from app.processing.ingest.presigned import admit_presigned_pointcloud

    storage, job, frozen = await _presigned_upload(monkeypatch, tmp_path)
    _decoder_with(
        monkeypatch,
        "lazrs.decompress_points_with_chunk_table = "
        "lambda *args: os.kill(os.getpid(), signal.SIGSEGV)",
    )

    with pytest.raises(HTTPException) as refusal:
        await admit_presigned_pointcloud(storage, job, frozen_key=frozen)

    assert (refusal.value.status_code, refusal.value.detail["code"]) == (
        422,
        "pointcloud_decode_failed",
    )
    assert not await storage.exists(job.user_metadata["s3_key"])
    assert not await storage.exists(frozen)


async def test_no_more_than_the_cap_of_children_decode_at_once(
    monkeypatch, tmp_path
) -> None:
    """Decodes past the cap wait for a slot, on the event loop."""
    path = _write(tmp_path, copc())
    _decoder_with(monkeypatch, "time.sleep(0.5)")
    running = peak = 0
    lock = threading.Lock()
    run = pointcloud_module.run_child

    def _run(argv, **kwargs):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        try:
            return run(argv, **kwargs)
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(pointcloud_module, "run_child", _run)
    cap = pointcloud_module.MAX_DECODE_CHILDREN

    await asyncio.gather(
        *(staged_pointcloud_metadata(path, "pointcloud") for _ in range(cap + 1))
    )

    assert peak == cap


def _slow_node(count: int) -> bytes:
    """A COPC whose one node holds ``count`` scattered points in one chunk."""
    rng = np.random.default_rng(7)
    point = np.dtype(
        [
            ("xyz", "<i4", 3),
            ("intensity", "<u2"),
            ("returns", "u1"),
            ("flags", "u1"),
            ("classification", "u1"),
            ("rest", "u1", 13),
        ]
    )
    points = np.zeros(count, dtype=point)
    points["xyz"] = rng.integers(0, (1000, 1000, 100), size=(count, 3))
    points["returns"] = 0x11
    points["classification"] = 2
    compressed = io.BytesIO()
    compressor = lazrs.LasZipCompressor(
        compressed, lazrs.LazVlr.new_for_compression(6, 0, True)
    )
    compressor.compress_many(points.tobytes())
    compressor.done()
    raw = compressed.getvalue()
    chunk = raw[8 : struct.unpack_from("<q", raw)[0]]
    return copc(count=count, points=points.tobytes(), chunk=lambda _: chunk)


async def test_the_event_loop_keeps_serving_while_a_large_node_decodes(
    tmp_path,
) -> None:
    path = _write(tmp_path, _slow_node(2_000_000))
    gaps: list[float] = []
    decoded = asyncio.Event()

    async def _tick() -> None:
        last = time.monotonic()
        while not decoded.is_set():
            await asyncio.sleep(0.005)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    ticker = asyncio.create_task(_tick())
    started = time.monotonic()
    try:
        assert await staged_pointcloud_metadata(path, "pointcloud")
    finally:
        elapsed = time.monotonic() - started
        decoded.set()
        await ticker

    # Decoded in this process, the node held the loop for about four fifths of
    # its decode; through the child the longest gap is scheduling noise.
    assert max(gaps) < elapsed / 2, (
        f"the loop stalled {max(gaps):.3f}s during a {elapsed:.3f}s decode"
    )


def test_only_the_decode_child_imports_lazrs() -> None:
    """No API or worker module loads the decoder, so none can decode in-process."""
    app_dir = Path(pointcloud_module.__file__).resolve().parents[2]
    importers = set()
    for path in app_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            if any(module.split(".")[0] == "lazrs" for module in modules):
                importers.add(path.relative_to(app_dir).as_posix())

    assert importers == {"processing/ingest/pointcloud_decode.py"}

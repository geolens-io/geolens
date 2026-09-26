"""Every point cloud read the whole-file limit exempts streams at most 16 MiB, checked against the serving path."""

import itertools
import uuid

from fastapi import HTTPException
from sqlalchemy import BigInteger
from starlette.requests import Request

from app.modules.catalog.datasets.api import router_pointcloud
from app.platform.http.stored_bytes import serve_stored_bytes
from app.processing.raster.models import DatasetAsset

_LIMIT = router_pointcloud._EXEMPT_RANGE_BYTES
_ATTEMPT = uuid.UUID("1b2c3d4e-5555-6666-7777-888899990000")
_ETAG = f'"{_ATTEMPT}"'
_MIB = 1024 * 1024

_RANGES = [
    None,
    "",
    "   ",
    "bytes=0-9",
    f"bytes=0-{_LIMIT - 1}",
    f"bytes=0-{_LIMIT}",
    "bytes=5-",
    "bytes=0-",
    f"bytes=-{_LIMIT}",
    f"bytes=-{_LIMIT + 1}",
    "bytes=-1",
    "bytes=-0",
    "bytes=0-9,20-29",
    "bytes=0-9,",
    "bytes=,0-9",
    "bytes=0-9, 0-9",
    "BYTES=0-9",
    "Bytes=0-9",
    "bytes= 0-9",
    " bytes=0-9 ",
    "bytes = 0-9",
    "bytes=0 - 9",
    "items=0-9",
    "bytes=9-0",
    "bytes=abc",
    "bytes=0-" + "9" * 19,
    "bytes=0-" + "9" * 25,
    "bytes=" + "9" * 19 + "-",
    "bytes=" + "9" * 25 + "-",
    "bytes=-" + "9" * 19,
    "bytes=-" + "9" * 25,
    "bytes=-" + "0" * 30 + "5",
    "bytes=" + "0" * 30 + "1-" + "0" * 30 + "9",
    f"bytes={10**19 - 5}-",
    f"bytes={2**63}-{2**63 + 5}",
]
_IF_RANGES = [
    None,
    _ETAG,
    f" {_ETAG} ",
    f"W/{_ETAG}",
    '"other"',
    "Sat, 26 Sep 2026 00:00:00 GMT",
    _ETAG.upper(),
]
_SIZES = [0, 1, 1000, _LIMIT - 1, _LIMIT, _LIMIT + 1, 10 * 1024 * _MIB, 2**63 - 1]
# The exemption reads the attempt as the path spells it; the route serves the
# canonical UUID's ETag.
_ATTEMPT_SPELLINGS = [
    str(_ATTEMPT),
    str(_ATTEMPT).upper(),
    _ATTEMPT.hex,
    "{" + str(_ATTEMPT) + "}",
    "urn:uuid:" + str(_ATTEMPT),
]


class _Store:
    """Records the read the serving path asks for, and yields one byte of it."""

    def __init__(self) -> None:
        self.read: tuple[str, int | None] | None = None
        self.opened: list = []

    async def _one_byte(self):
        yield b"x"

    def get_stream(self, key: str):
        self.read = ("whole", None)
        self.opened.append(self._one_byte())
        return self.opened[-1]

    def get_range_stream(self, key: str, start: int, length: int):
        self.read = ("range", length)
        self.opened.append(self._one_byte())
        return self.opened[-1]

    async def size(self, key: str) -> int:
        return 0


def _request(method: str, headers: list[tuple[str, str]], attempt: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/datasets/x/copc/y/data.copc.laz",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
            "path_params": {"attempt_id": attempt},
        }
    )


async def _streamed(method: str, headers: list[tuple[str, str]], size: int) -> int:
    """How many bytes of an object of ``size`` the serving path streams for this read."""
    store = _Store()
    try:
        await serve_stored_bytes(
            _request(method, headers, str(_ATTEMPT)),
            store,
            "key",
            total_bytes=size,
            media_type="application/vnd.laszip+copc",
            etag=_ETAG,
            strict=True,
        )
    except HTTPException:
        return 0
    finally:
        for stream in store.opened:
            await stream.aclose()
    if method == "HEAD" or store.read is None:
        return 0
    kind, length = store.read
    return size if kind == "whole" else length


async def test_no_exempt_read_streams_more_than_16_mib() -> None:
    """For any method, Range, If-Range, attempt spelling and size, an exempt read streams at most 16 MiB."""
    breaches, exempt, over_the_cap = [], 0, 0
    for method, byte_range, if_range, size in itertools.product(
        ["GET", "HEAD"], _RANGES, _IF_RANGES, _SIZES
    ):
        headers = [("Range", byte_range)] if byte_range is not None else []
        if if_range is not None:
            headers.append(("If-Range", if_range))
        streamed = await _streamed(method, headers, size)
        over_the_cap += streamed > _LIMIT
        for spelling in _ATTEMPT_SPELLINGS:
            if not router_pointcloud._reads_one_small_range(
                _request(method, headers, spelling)
            ):
                continue
            exempt += 1
            if streamed > _LIMIT:
                breaches.append((method, byte_range, if_range, size, spelling))

    assert breaches == []
    assert exempt > 0, "precondition: some reads are exempt"
    assert over_the_cap > 0, "precondition: some reads stream more than 16 MiB"


def test_the_exemption_parses_ranges_against_a_size_no_object_can_have() -> None:
    """``_ANY_SIZE`` stays above the largest size the pointer row's column holds."""
    column = DatasetAsset.__table__.c.size_bytes.type
    assert isinstance(column, BigInteger)
    assert router_pointcloud._ANY_SIZE > 2**63 - 1

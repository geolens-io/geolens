"""A test's database engine does not outlive its `client` fixture.

An xdist worker runs thousands of tests in one process. Whatever a finished
test leaves reachable is walked again by every later full GC pass, and that
pass runs inside whichever test happens to trigger it, so a retained engine
per test turns into multi-second stalls in unrelated tests late in a run.
"""

import gc
import weakref

import pytest
from httpx import AsyncClient


@pytest.fixture
def engine_refs():
    """Weak references checked after every other fixture of the test is torn down."""
    refs: list[weakref.ref] = []
    yield refs
    gc.collect()
    assert [ref for ref in refs if ref() is not None] == [], (
        "the client fixture's engine is still reachable after the test"
    )


async def test_the_engine_is_released_when_the_client_fixture_ends(
    engine_refs, client: AsyncClient, admin_auth_header: dict
) -> None:
    import app.core.db as db_module

    # A request resolves get_db through the fixture's override, the way every
    # test's requests do.
    resp = await client.get("/maps/", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text

    engine_refs.append(weakref.ref(db_module.engine))

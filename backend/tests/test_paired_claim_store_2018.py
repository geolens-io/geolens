"""Pin #2018's shared claim store: the #1903 semantics, on a store two workers share.

The counting invariant these back is exercised end to end against both
backends in test_rate_limits.py; this file pins the store primitives that
invariant rests on.
"""

import fakeredis
import pytest
import structlog

from app.platform.ratelimit_claims import (
    CLAIM_TTL_SECONDS,
    SharedClaimStore,
    claim_key,
)

_PARTS = ("203.0.113.7", "tenant:cities")


@pytest.fixture
def store() -> SharedClaimStore:
    return SharedClaimStore(fakeredis.FakeStrictRedis(decode_responses=True))


def test_a_claim_is_single_use_and_only_the_other_route_redeems_it(
    store: SharedClaimStore,
):
    assert store.record(_PARTS, "datasets") is True
    assert store.consume(_PARTS, "facets") is True
    assert store.consume(_PARTS, "facets") is False


def test_a_same_route_repeat_is_never_exempt_and_takes_the_claim_with_it(
    store: SharedClaimStore,
):
    """A burst against one route still pays per request.

    ``GETDEL`` is one round trip, which is what stops two workers redeeming
    one claim, and the price is the only divergence from the process-local
    registry: a same-route caller reads its own claim and destroys it. That
    can cost the sibling an exemption, never grant an extra one.
    """
    store.record(_PARTS, "facets")
    assert store.consume(_PARTS, "facets") is False
    assert store.consume(_PARTS, "datasets") is False


def test_a_client_that_returns_bytes_still_refuses_a_same_route_repeat():
    """The route comparison must not depend on ``decode_responses``.

    Bytes never compare equal to a str, so a client built without it would
    read a same-route caller's own claim as the sibling's and exempt it.
    """
    store = SharedClaimStore(fakeredis.FakeStrictRedis())

    store.record(_PARTS, "facets")

    assert store.consume(_PARTS, "facets") is False


def test_a_second_writer_does_not_extend_a_standing_claim():
    """``NX``: whoever claimed first keeps the route and the deadline."""
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    store = SharedClaimStore(client)

    store.record(_PARTS, "datasets")
    store.record(_PARTS, "facets")

    assert client.get(claim_key(_PARTS)) == "datasets"


def test_a_claim_carries_the_pairing_window_as_its_ttl():
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    SharedClaimStore(client).record(_PARTS, "datasets")
    assert client.ttl(claim_key(_PARTS)) == CLAIM_TTL_SECONDS


def test_an_ipv6_client_cannot_shift_the_key_onto_a_neighbours(
    store: SharedClaimStore,
):
    """The key is length-prefixed before it is hashed.

    Both components contain ``:`` -- one is an IPv6 address, the other is
    caller-supplied text -- so a plain join would let a /64 holder pick low
    bits that move the split and land on a neighbour's key.
    """
    mine = ("2001:db8::1", "ab")
    neighbours = ("2001:db8::1a", "b")

    assert claim_key(mine) != claim_key(neighbours)
    store.record(mine, "datasets")
    assert store.consume(neighbours, "facets") is False


def test_a_store_error_answers_none_rather_than_exempt():
    """None is the signal to fall back; True would be a free exemption."""

    class _DeadClient:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("claim store unreachable")

        def getdel(self, *_args, **_kwargs):
            raise ConnectionError("claim store unreachable")

    dead = SharedClaimStore(_DeadClient())
    assert dead.record(_PARTS, "datasets") is None
    assert dead.consume(_PARTS, "facets") is None


def test_an_outage_is_logged_once_per_outage_not_once_per_request():
    """This runs inside ``exempt_when``, so per-call logging is per request."""

    class _FlakyClient:
        healthy = False

        def getdel(self, *_args, **_kwargs):
            if not self.healthy:
                raise ConnectionError("claim store unreachable")
            return None

    client = _FlakyClient()
    flaky = SharedClaimStore(client)

    with structlog.testing.capture_logs() as captured:
        for _ in range(3):
            flaky.consume(_PARTS, "facets")
        client.healthy = True
        flaky.consume(_PARTS, "facets")
        client.healthy = False
        flaky.consume(_PARTS, "facets")

    outages = [e for e in captured if e["event"] == "paired_claim_store_unavailable"]
    assert len(outages) == 2, [e["event"] for e in captured]

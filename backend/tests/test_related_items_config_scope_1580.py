"""Related items compare stored vectors inside ONE space (#1580).

`get_nearest_record_ids`, and the `get_record_embedding` / `get_embedding_distances`
pair behind it, selected candidate rows from `catalog.record_embeddings` filtered
by neither `model_name` nor, since #1546, `config_fingerprint`. So related-items
compared one record's stored vector against every other record's, across model and
configuration spaces, and returned cosine distances that were well-formed and
meaningless whenever the table held more than one space.

The rule here is NOT the one the search path uses, and the difference is the
point. Semantic search compares a FRESH query vector against stored rows, so the
live configuration is the right question. Both sides of this comparison are
STORED rows, so the question is the ANCHOR row's: same model and same stamp as
the row the comparison starts from. A record embedded under a superseded
configuration finds its own-space neighbours, or finds none, and never crosses.
`test_an_anchor_from_a_superseded_configuration_still_finds_its_own_space` is the
one that fails if anyone reaches for the live configuration instead.

Three readers had to learn it, not one. The selection picks the candidates; the
scoring turns them into the similarity percentage the UI prints; and the anchor
read decides which of the anchor's own rows both of those are about. Fixing only
the first would have moved the defect one layer out, to the right neighbours
scored in the wrong space, which is what
`test_a_neighbour_is_scored_in_the_anchors_own_space` exists to catch.

Every test seeds its own model names (the `space` fixture). The database is
shared across this module, and every row this suite writes is a candidate
neighbour for every other test in it; without the partition the assertions that
name an exact result set would be reporting on their neighbours' fixtures.

Requirements:
  - Docker database must be running (docker compose up db)
  - Run with: set -a && source ../.env.test && set +a
              uv run pytest tests/test_related_items_config_scope_1580.py -v
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.processing.embeddings import helpers
from app.processing.embeddings.helpers import (
    embedding_config_fingerprint,
    resolve_embedding_config_fingerprint,
)
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_DIMS = 1536


@pytest.fixture(autouse=True)
def _fresh_has_embeddings_cache():
    """Clear the module-global has_embeddings cache before every test.

    Same hazard class as `test_related_datasets.py` and `test_hybrid_search.py`:
    this file inserts RecordEmbedding rows, so under xdist a stale cached False
    would starve the vector path and our own inserts can poison True for later
    tests.
    """
    helpers._has_embeddings_cache.clear()
    yield


@pytest.fixture
def space():
    """Model names and two configuration stamps, unique to one test.

    The model names are what isolate a test from its module neighbours: rows
    from another test carry another model and are excluded by the same predicate
    under test. That is deliberate rather than convenient — it means a test that
    names an exact result set is describing its own fixture, and it means the
    isolation itself fails loudly if the model half of the predicate is ever
    dropped, because every other test's rows come flooding in.

    `config_a` and `config_b` differ ONLY in the endpoint. Same model name, same
    width: exactly the pair `model_name` cannot tell apart, which is why #1546
    added the stamp and why a model predicate alone would not close #1580.
    """
    tag = uuid.uuid4().hex[:8]
    model = f"related-1580-{tag}"
    return SimpleNamespace(
        model=model,
        other_model=f"related-1580-other-{tag}",
        config_a=embedding_config_fingerprint(model, _DIMS, "https://a.invalid/v1"),
        config_b=embedding_config_fingerprint(model, _DIMS, "https://b.invalid/v1"),
    )


def _vec(base: list[float]) -> list[float]:
    """A 1536-dim vector from a short base, zero-padded."""
    return (base + [0.0] * _DIMS)[:_DIMS]


# The anchor's direction and two others at known cosine distances from it.
_V_ANCHOR = _vec([1.0, 0.0, 0.0])
_V_NEAR = _vec([0.9, 0.1, 0.0])  # distance ~0.0061 from _V_ANCHOR
_V_MID = _vec([0.6, 0.8, 0.0])  # distance 0.4, comfortably inside the 0.7 gate

# 1 - the cosine distance between _V_ANCHOR and _V_NEAR, which is the similarity
# the endpoint prints for that pair. Stated once so the scoring test can pin the
# exact number rather than a range.
_SIMILARITY_ANCHOR_TO_NEAR = 0.9939


async def _add_row(
    session,
    record_id: uuid.UUID,
    vector: list[float],
    *,
    model_name: str,
    config_fingerprint: str | None = None,
    updated_at: datetime | None = None,
) -> RecordEmbedding:
    """Insert one `record_embeddings` row with an explicit space and age.

    `updated_at` is set explicitly rather than left to `server_default=now()`,
    because `now()` is the TRANSACTION timestamp: two rows written in one
    transaction get the same value, and the anchor's "most recently written row"
    rule would then be decided by the model-name tiebreak instead of by
    recency. Tests that care about which row is the anchor state the ages rather
    than inherit them.
    """
    row = RecordEmbedding(
        record_id=record_id,
        embedding=vector,
        model_name=model_name,
        config_fingerprint=config_fingerprint,
        content_hash=uuid.uuid4().hex[:64],
    )
    if updated_at is not None:
        row.updated_at = updated_at
    session.add(row)
    await session.commit()
    return row


async def _dataset(session, name: str):
    user_id = await get_user_id(session, "admin")
    return await create_dataset(session, created_by=user_id, name=name)


async def _related(client: AsyncClient, headers: dict, dataset_id) -> dict[str, float]:
    """The endpoint's answer as ``{name: similarity}``."""
    resp = await client.get(f"/datasets/{dataset_id}/related/", headers=headers)
    assert resp.status_code == 200, resp.text
    return {item["name"]: item["similarity"] for item in resp.json()["items"]}


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


async def test_related_items_do_not_cross_a_configuration_boundary(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """The headline case: one model name, two endpoints, two vector spaces.

    The foreign row carries the anchor's OWN vector, so it is the nearest
    neighbour that exists, at distance 0.0. Nothing but the configuration
    predicate can keep it out, and a filter that fails open surfaces it first.

    The same-space neighbour is asserted present in the same test rather than in
    a sibling, because a predicate that rejected everything would pass the first
    assertion and break the feature. This is a scoping fix, not a refusal.
    """
    anchor = await _dataset(test_db_session, "Cfg Anchor")
    same_space = await _dataset(test_db_session, "Cfg Same Space")
    foreign = await _dataset(test_db_session, "Cfg Foreign")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        same_space.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        foreign.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_b,
    )

    names = set(await _related(client, admin_auth_header, anchor.id))

    assert "Cfg Foreign" not in names, (
        f"related items returned {sorted(names)}. That row is a vector from "
        f"another endpoint under the same model name; the cosine distance to it "
        f"is 0.0 and it means nothing."
    )
    assert "Cfg Same Space" in names, (
        f"related items returned {sorted(names)}. The scoping must not cost a "
        f"record its own-configuration neighbours: a filter that rejects "
        f"everything passes the assertion above and deletes the feature."
    )


async def test_related_items_do_not_cross_a_model_boundary(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """The older half of the same defect, which predates the stamp entirely.

    A fingerprint predicate without a model predicate would be incoherent, so
    #1580 adds both, through `usable_by_config` — the one expression of the pair
    that semantic search, the non-force backfill and the coverage panel already
    apply. A model swap is how a catalog gets here: the old model's rows stay in
    the table, exactly as near the anchor as their replacements.
    """
    anchor = await _dataset(test_db_session, "Model Anchor")
    same_model = await _dataset(test_db_session, "Model Same")
    other_model = await _dataset(test_db_session, "Model Other")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        same_model.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        other_model.record_id,
        _V_ANCHOR,
        model_name=space.other_model,
        config_fingerprint=space.config_a,
    )

    names = set(await _related(client, admin_auth_header, anchor.id))

    assert "Model Other" not in names, (
        f"related items returned {sorted(names)}. Two models' vectors are not "
        f"comparable however similar the numbers look."
    )
    assert "Model Same" in names, f"related items returned {sorted(names)}"


async def test_an_anchor_from_a_superseded_configuration_still_finds_its_own_space(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """The rule is the ANCHOR row's pair, never the live configuration's.

    This is where related-items parts company with semantic search. There, one
    side of the comparison is a vector made moments ago, so "can the live
    configuration use this row" is the right question and #1546 answers it.
    Here both sides are stored rows, and asking the live configuration would
    empty the feature for every record not yet re-embedded, while doing nothing
    about the actual defect, which is comparing two stored rows from different
    spaces.

    Neither stamp in this test is the live one, and that is asserted rather than
    assumed. Both records are found anyway.
    """
    live = await resolve_embedding_config_fingerprint(test_db_session)
    assert live not in (space.config_a, space.config_b), (
        f"precondition: this test needs both stamps to be foreign to the live "
        f"configuration, and the live fingerprint resolved to {live!r}"
    )

    anchor = await _dataset(test_db_session, "Superseded Anchor")
    neighbour = await _dataset(test_db_session, "Superseded Neighbour")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        neighbour.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )

    names = set(await _related(client, admin_auth_header, anchor.id))

    assert "Superseded Neighbour" in names, (
        f"related items returned {sorted(names)} for an anchor stamped with a "
        f"configuration that is no longer live. Both rows came out of the same "
        f"one, so they are comparable; filtering on the live configuration "
        f"instead would answer nothing here and still compare across spaces "
        f"wherever the live configuration happened to match."
    )


async def test_an_unstamped_anchor_matches_unstamped_rows_of_its_model(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """Grandfathering, read from the anchor side (#1546's NULL arm).

    Every row in the table before migration 0052 is unstamped, and #1546 kept
    them usable rather than empty semantic search on upgrade. The same has to
    hold here, or related-items goes blank the morning after an upgrade on a
    catalog where nothing is wrong.

    `usable_by_config(model, None)` renders `config_fingerprint IS NULL`, so an
    unstamped anchor selects the unstamped rows of its own model. A stamped row
    belongs to a configuration this one cannot be compared against, and the
    second assertion is the counterfactual for the first: without it this test
    would pass against a reader that ignored the stamp entirely, which is the
    state being fixed.
    """
    anchor = await _dataset(test_db_session, "Legacy Anchor")
    legacy_peer = await _dataset(test_db_session, "Legacy Peer")
    stamped = await _dataset(test_db_session, "Legacy Stamped")

    await _add_row(test_db_session, anchor.record_id, _V_ANCHOR, model_name=space.model)
    await _add_row(
        test_db_session, legacy_peer.record_id, _V_NEAR, model_name=space.model
    )
    await _add_row(
        test_db_session,
        stamped.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )

    names = set(await _related(client, admin_auth_header, anchor.id))

    assert "Legacy Peer" in names, (
        f"related items returned {sorted(names)}. An all-unstamped catalog is "
        f"what every instance looks like the day it upgrades, and it must "
        f"behave exactly as it did before."
    )
    assert "Legacy Stamped" not in names, (
        f"related items returned {sorted(names)}. A stamped row belongs to a "
        f"known configuration and an unstamped one does not, so the two are not "
        f"comparable in the direction that matters."
    )


# ---------------------------------------------------------------------------
# One layer out: the number the user sees
# ---------------------------------------------------------------------------


async def test_a_neighbour_is_scored_in_the_anchors_own_space(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """Selecting the right neighbour is half of it; scoring it is the other half.

    `get_embedding_distances` re-reads every selected neighbour to turn it into
    the similarity percentage the UI prints, and it carried no space predicate
    at all. A record may hold one row per model (`uq_record_embedding_model` is
    `(record_id, model_name)`), so a neighbour that survived the selection on its
    same-space row could still be SCORED off one of its others: the query
    returned every row for that record and the dict comprehension behind it
    keeps whichever came last.

    The neighbour here holds three rows. Its true one is near the anchor and was
    written first; the two foreign ones sit at distance 0.4 and were written
    after, so under an unscoped read the value that survives is a foreign one.
    Pinning the exact number rather than a range is what makes the assertion
    independent of which row the planner happens to return last: any foreign
    pick fails it, whichever one wins.
    """
    anchor = await _dataset(test_db_session, "Scored Anchor")
    neighbour = await _dataset(test_db_session, "Scored Neighbour")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        neighbour.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    for suffix in ("1", "2"):
        await _add_row(
            test_db_session,
            neighbour.record_id,
            _V_MID,
            model_name=f"{space.other_model}-{suffix}",
            config_fingerprint=space.config_a,
        )

    items = await _related(client, admin_auth_header, anchor.id)

    assert "Scored Neighbour" in items, (
        f"the neighbour was not selected at all, so this test proves nothing "
        f"about scoring; got {items}"
    )
    assert items["Scored Neighbour"] == pytest.approx(
        _SIMILARITY_ANCHOR_TO_NEAR, abs=5e-4
    ), (
        f"the neighbour scored {items['Scored Neighbour']}, which is its "
        f"distance from the anchor measured in a space the anchor is not in. "
        f"0.6 is what the foreign rows answer; {_SIMILARITY_ANCHOR_TO_NEAR} is "
        f"the true one."
    )


# ---------------------------------------------------------------------------
# One anchor, three readers
# ---------------------------------------------------------------------------


async def test_the_selection_follows_the_anchors_most_recent_row(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """A model swap mid-flight: the anchor holds a row in each of two spaces.

    Both peers are the same distance from the vector the anchor was re-embedded
    to, so distance alone cannot separate them and the 0.7 gate does not either.
    The only thing that does is which space the comparison is in, and that comes
    from the anchor's newest row.

    Before #1580 the anchor was whatever an unordered `LIMIT 1` returned and
    there was no predicate at all, so both peers came back: one of them a vector
    from the model this record used to be embedded under.
    """
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)

    anchor = await _dataset(test_db_session, "Swap Anchor")
    new_peer = await _dataset(test_db_session, "Swap New Peer")
    old_peer = await _dataset(test_db_session, "Swap Old Peer")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_MID,
        model_name=space.other_model,
        config_fingerprint=space.config_a,
        updated_at=old,
    )
    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_b,
        updated_at=new,
    )
    await _add_row(
        test_db_session,
        new_peer.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_b,
        updated_at=new,
    )
    await _add_row(
        test_db_session,
        old_peer.record_id,
        _V_NEAR,
        model_name=space.other_model,
        config_fingerprint=space.config_a,
        updated_at=old,
    )

    names = set(await _related(client, admin_auth_header, anchor.id))

    assert names == {"Swap New Peer"}, (
        f"related items returned {sorted(names)}. The anchor's most recent row "
        f"is its new-model one, so the new-model peer is its neighbour and the "
        f"old-model peer is a vector from a space this comparison is not in."
    )


async def test_the_anchor_is_the_most_recently_written_row(test_db_session, space):
    """Which row, stated once, because three readers depend on the answer.

    Before #1580 this was whatever the planner returned from an unordered
    `LIMIT 1`. Most recent is the least surprising reading of "this record's
    vector" after a swap, it is the one a re-embed moves, and it is stable: the
    model-name tiebreak is there so two rows written in one transaction, which
    share `now()`, still resolve to one answer rather than to chance.

    The newer row here is the OTHER-model one, deliberately, so an
    implementation that ordered by model name alone would answer the older.
    """
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    record = await _dataset(test_db_session, "Anchor Pick")

    await _add_row(
        test_db_session,
        record.record_id,
        _V_MID,
        model_name=space.other_model,
        config_fingerprint=space.config_a,
        updated_at=new,
    )
    await _add_row(
        test_db_session,
        record.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_b,
        updated_at=old,
    )

    anchor = await helpers.get_anchor_embedding_row(test_db_session, record.record_id)

    assert anchor is not None
    _, model_name, config_fingerprint = anchor
    assert (model_name, config_fingerprint) == (space.other_model, space.config_a), (
        f"the anchor resolved to ({model_name}, {config_fingerprint}), not the "
        f"most recently written row"
    )


async def test_the_port_hands_the_anchors_identity_to_its_caller(
    test_db_session, space
):
    """`get_record_embedding` returns the space, not just the numbers.

    A list of floats does not say which model or endpoint produced it, so a
    caller handed only the vector cannot hold anything downstream to the
    anchor's space. That is why the port's shape changed and why
    EXTENSION_API_VERSION moved with it.

    The last assertion is the one that matters most and is the reason both go
    through `get_anchor_embedding_row`: the identity has to name the SAME row
    `get_nearest_record_ids` ranks against. Two independent `LIMIT 1` reads of
    one record could return different rows, and then the neighbours would be
    ranked around one vector and scored from another.
    """
    record = await _dataset(test_db_session, "Port Anchor")
    await _add_row(
        test_db_session,
        record.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )

    returned = await DefaultCatalogPort().get_record_embedding(
        test_db_session, record.record_id
    )

    assert returned is not None
    embedding, model_name, config_fingerprint = returned
    assert list(embedding)[:3] == [1.0, 0.0, 0.0]
    assert (model_name, config_fingerprint) == (space.model, space.config_a)
    assert returned == await helpers.get_anchor_embedding_row(
        test_db_session, record.record_id
    ), "the port and the ranking helper must resolve the same anchor row"


# ---------------------------------------------------------------------------
# Review r2: grandfathering is for the side that has no choice
# ---------------------------------------------------------------------------


async def test_a_stamped_anchor_does_not_reach_legacy_unstamped_rows(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """fix(#1580 review r2): the stored-vs-stored predicate does not grandfather.

    `usable_by_config` matches an unstamped row against any fingerprint, and
    that is right for SEARCH: its caller holds a vector made moments ago, and on
    upgrade day every row in the table is unstamped, so refusing them would
    return nothing until a catalog-wide re-embed finished. The unstamped rows
    are all there is.

    Here both sides are stored and a STAMPED anchor is evidence the catalog is
    past that morning and at least partly regenerated. The catalog where this
    bites is an endpoint change followed by a partial re-embed: the rows still
    carrying NULL are most likely the ones in the OLD space, and comparing them
    against a new-space anchor is precisely the well-formed meaningless distance
    this PR removes — on the records least likely to be looked at twice.

    The legacy row here carries the anchor's own vector, so it is the nearest
    neighbour that exists and nothing but the predicate can keep it out.
    """
    anchor = await _dataset(test_db_session, "Stamped Anchor")
    same_space = await _dataset(test_db_session, "Stamped Peer")
    legacy = await _dataset(test_db_session, "Legacy Leftover")

    await _add_row(
        test_db_session,
        anchor.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(
        test_db_session,
        same_space.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
    )
    await _add_row(test_db_session, legacy.record_id, _V_ANCHOR, model_name=space.model)

    items = await _related(client, admin_auth_header, anchor.id)

    assert "Legacy Leftover" not in items, (
        f"related items returned {sorted(items)}. That row predates the stamp, "
        f"so which space it is in is unknown — and on the catalog this matters "
        f"for, a partial re-embed, unknown means the old one."
    )
    assert "Stamped Peer" in items, (
        f"related items returned {sorted(items)}; refusing NULL must not cost a "
        f"record its own-configuration neighbours"
    )


def test_both_stored_readers_use_the_stored_anchor_predicate():
    """The scoring query must not keep search's grandfathering either.

    Asserted structurally rather than through data, because the data case is
    unreachable: ``uq_record_embedding_model`` is ``(record_id, model_name)``, so
    one record cannot hold both a stamped and an unstamped row of the same
    model, and a neighbour whose only row is unstamped is already removed by the
    selection filter. There is no catalog that exercises the scoring query's
    NULL arm on its own.

    Which is exactly why it needs pinning some other way. The selection and the
    scoring are two independent readers of the same rule — fix(#1580) already
    had to fix this pair once, when scoping the selection left the scoring
    reporting distances from a foreign model — and a rule that cannot drift
    apart in a test can still drift apart in the source.

    A test that only named the wanted call would pass against a file that called
    both, so the unwanted one is asserted absent too.

    Comments are stripped and the CALL form is matched, not the bare name. The
    first version of this scanned raw source and failed on the explanatory
    comment beside the call it was checking — a predicate that cannot tell a
    mention from a use answers a question nobody asked.
    """
    import inspect

    from app.platform.extensions import defaults_catalog_port
    from app.processing.embeddings import helpers

    def _code(fn) -> str:
        return "\n".join(
            line
            for line in inspect.getsource(fn).splitlines()
            if not line.strip().startswith("#")
        )

    readers = {
        "selection": _code(helpers.get_nearest_record_ids),
        "scoring": _code(
            defaults_catalog_port.DefaultCatalogPort.get_embedding_distances
        ),
    }

    for name, source in readers.items():
        assert "usable_by_stored_anchor(" in source, (
            f"the {name} query does not call the stored-vs-stored predicate"
        )
        assert "usable_by_config(" not in source, (
            f"the {name} query still calls search's predicate, which matches an "
            f"unstamped row against a stamped anchor. Right for a fresh query "
            f"vector, wrong for two stored rows."
        )


async def test_an_all_legacy_catalog_still_finds_its_neighbours(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space
):
    """The half that must NOT change: upgrade day still works.

    Refusing NULL against a stamped anchor is only defensible because an
    unstamped anchor keeps matching unstamped rows. Without this the morning
    after migration 0052 — when every row in the table is unstamped — related
    items would go blank on a catalog where nothing is wrong, which is the
    outcome #1546's grandfathering exists to prevent.
    """
    anchor = await _dataset(test_db_session, "All Legacy Anchor")
    peer = await _dataset(test_db_session, "All Legacy Peer")

    await _add_row(test_db_session, anchor.record_id, _V_ANCHOR, model_name=space.model)
    await _add_row(test_db_session, peer.record_id, _V_NEAR, model_name=space.model)

    items = await _related(client, admin_auth_header, anchor.id)

    assert "All Legacy Peer" in items, (
        f"related items returned {sorted(items)} on an all-unstamped catalog, "
        f"which is what every instance looks like the day it upgrades"
    )


# ---------------------------------------------------------------------------
# Review r2: one read, not two
# ---------------------------------------------------------------------------


async def test_a_commit_between_the_two_reads_cannot_split_the_anchor(
    client: AsyncClient, admin_auth_header: dict, test_db_session, space, monkeypatch
):
    """fix(#1580 review r2): the ranking and the scoring share ONE anchor read.

    `_load_self_record_and_embedding` read the anchor to score with, and
    `get_nearest_record_ids` read it again to rank against. Two reads under READ
    COMMITTED, so a worker committing a newer row for this record between them
    left the selection anchored on the new vector and the scoring on the old —
    wrong distances, or nothing at all when the two spaces do not overlap. A v9
    overlay could pick differently again, since the method only received a
    record id.

    The commit is driven INTO that window rather than merely before or after it:
    the second call to the anchor reader publishes a newer row first. With the
    anchor passed in there is no second call, so the newer row cannot influence
    anything, and `reads` proves the window was actually entered under the old
    shape and closed under this one.
    """
    from app.processing.embeddings import helpers

    anchor_ds = await _dataset(test_db_session, "Split Anchor")
    peer = await _dataset(test_db_session, "Split Peer")

    await _add_row(
        test_db_session,
        anchor_ds.record_id,
        _V_ANCHOR,
        model_name=space.model,
        config_fingerprint=space.config_a,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _add_row(
        test_db_session,
        peer.record_id,
        _V_NEAR,
        model_name=space.model,
        config_fingerprint=space.config_a,
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    reads = {"count": 0}
    real_reader = helpers.get_anchor_embedding_row

    async def _committing_reader(session, record_id):
        reads["count"] += 1
        if reads["count"] == 2 and record_id == anchor_ds.record_id:
            # The interloper: a newer row in a DIFFERENT space, landing exactly
            # between the seed read and the neighbour selection.
            await _add_row(
                test_db_session,
                anchor_ds.record_id,
                _V_MID,
                model_name=space.other_model,
                config_fingerprint=space.config_b,
                updated_at=datetime(2026, 6, 1, tzinfo=UTC),
            )
        return await real_reader(session, record_id)

    monkeypatch.setattr(helpers, "get_anchor_embedding_row", _committing_reader)

    items = await _related(client, admin_auth_header, anchor_ds.id)

    assert reads["count"] == 1, (
        f"the anchor was read {reads['count']} times. Two reads is the defect: "
        f"whatever they return, nothing makes them the same row."
    )
    assert "Split Peer" in items, (
        f"related items returned {sorted(items)}. The seed's own space has a "
        f"neighbour in it; a selection anchored on a row the scoring never saw "
        f"finds nothing it can then score."
    )

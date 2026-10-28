"""Live-provider evals: AI metadata drafts state only what the dataset shows.

A steward reviewing a draft must be able to tell facts from guesses. The
fixture is a parks layer whose metadata supports some claims and not others:

* the extent and the borough sample values place it in New York City, so
  naming the city is grounded;
* there is no date column and no temporal extent, so any time period is a
  guess;
* nothing names a publisher, an audience or a purpose, so those are guesses
  too.

Each case drives the real metadata operation, from ``_build_dataset_context``
through the provider, with only the dataset lookup faked. A draft passes when
every sentence making an unsupported claim carries the ``(inferred)`` marker
(see ``tests/ai_metadata_grounding.py``), and keywords name no time and no
place the fixture does not support.

## Cost and gating

Live-provider, real tokens. SKIPPED unless ``RUN_AI_EVALS=1``::

    make ai-evals
    # or, this file only:
    cd backend && set -a && source ../.env.test && set +a && \\
        RUN_AI_EVALS=1 uv run pytest tests/evals/test_metadata_grounding_evals.py -v

The metadata model is the provider's light model (``LLM_MODEL_LIGHT`` or
``OPENAI_MODEL_LIGHT``). Each draft is one request; the suite stops spending
once it reaches ``SUITE_TOKEN_BUDGET``.
"""

import os
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

import app.processing.ai.metadata_service as metadata_service
from tests.ai_metadata_grounding import ungrounded_keywords, unsupported_claims

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_AI_EVALS") != "1",
        reason="live-provider AI evals; set RUN_AI_EVALS=1 to run",
    ),
]

# One draft is a ~1k-token prompt and at most 1024 output tokens; reasoning
# models spend more. The suite has five drafts.
DRAFT_TOKEN_BUDGET = 6_000
SUITE_TOKEN_BUDGET = 25_000

_DATASET_ID = "dddddddd-4444-4444-8444-dddddddddddd"
_spent = {"tokens": 0}


def _parks_dataset() -> SimpleNamespace:
    record = SimpleNamespace(
        title="Parks Properties",
        summary=None,
        lineage_summary=None,
        source_organization=None,
        # The five boroughs of New York City.
        spatial_extent=from_shape(box(-74.2557, 40.4961, -73.7004, 40.9156), srid=4326),
        access_constraints=None,
        keywords=[],
        temporal_start=None,
        temporal_end=None,
        record_type="dataset",
    )
    return SimpleNamespace(
        record=record,
        geometry_type="MultiPolygon",
        feature_count=2041,
        srid=4326,
        source_format="GeoJSON",
        source_filename="parks_properties.geojson",
        source_url=None,
        original_srid=2263,
        table_name="eval_parks_properties",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "borough", "type": "text"},
            {"name": "acres", "type": "double precision"},
            {"name": "typecategory", "type": "text"},
            {"name": "geom", "type": "geometry(MultiPolygon,4326)"},
        ],
        sample_values={
            "name": ["Central Park", "Prospect Park", "Flushing Meadows Corona Park"],
            "borough": ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"],
            "acres": [840.01, 526.25, 897.69],
            "typecategory": ["Flagship Park", "Neighborhood Park", "Playground"],
        },
        attributes=[],
        quality_detail={
            "geometry_validity_pct": 99.6,
            "attribute_completeness_pct": 97.1,
        },
        quality_statement=None,
    )


class _Port:
    async def get_dataset_with_attributes(self, _session, _dataset_id):
        return _parks_dataset()

    async def get_column_null_cardinality(self, *_args, **_kwargs):
        return {}

    async def get_catalog_vocabulary(self, *_args, **_kwargs):
        return []


@pytest.fixture(autouse=True)
def _offline_metadata(monkeypatch):
    """Fake the dataset lookup and count the tokens each draft spends."""
    if _spent["tokens"] >= SUITE_TOKEN_BUDGET:
        pytest.skip(f"suite token budget of {SUITE_TOKEN_BUDGET} spent")
    metadata_service._dataset_context_cache.clear()
    calls: list[int] = []

    async def record_token_usage(*, input_tokens, output_tokens, **_kwargs):
        calls.append(input_tokens + output_tokens)
        _spent["tokens"] += input_tokens + output_tokens

    async def send_samples(_session):
        return True

    async def no_related_keywords(*_args, **_kwargs):
        return []

    monkeypatch.setattr(metadata_service, "record_token_usage", record_token_usage)
    monkeypatch.setattr(metadata_service, "_should_send_sample_values", send_samples)
    monkeypatch.setattr(
        metadata_service, "_get_related_keywords_from_embeddings", no_related_keywords
    )
    yield calls
    print(f"tokens: {sum(calls)}")
    assert sum(calls) <= DRAFT_TOKEN_BUDGET, f"draft spent {sum(calls)} tokens"


async def test_summary_marks_every_unsupported_claim(_offline_metadata):
    result = await metadata_service.generate_summary_draft(
        None, _DATASET_ID, port=_Port()
    )
    print(f"\nsummary: {result.draft}")

    claims = unsupported_claims(result.draft, ("time", "audience", "use", "publisher"))
    assert not claims, f"unmarked claims: {claims}"


async def test_summary_names_the_grounded_region(_offline_metadata):
    result = await metadata_service.generate_summary_draft(
        None, _DATASET_ID, port=_Port()
    )

    assert "new york" in result.draft.lower(), result.draft


async def test_keywords_name_no_unsupported_time_or_place(_offline_metadata):
    result = await metadata_service.generate_keyword_suggestions(
        None,
        _DATASET_ID,
        port=_Port(),
        user=SimpleNamespace(id=None),
        user_roles=set(),
    )
    keywords = [kw.model_dump() for kw in result.keywords]
    print(f"\nkeywords: {keywords}")

    assert not ungrounded_keywords(keywords), keywords


async def test_lineage_states_only_recorded_processing(_offline_metadata):
    result = await metadata_service.generate_lineage_draft(
        None, _DATASET_ID, port=_Port()
    )
    print(f"\nlineage: {result.draft}")

    claims = unsupported_claims(result.draft, ("publisher", "processing", "time"))
    assert not claims, f"unmarked claims: {claims}"


async def test_quality_statement_claims_no_unmeasured_quality(_offline_metadata):
    result = await metadata_service.generate_quality_statement_draft(
        None, _DATASET_ID, port=_Port()
    )
    print(f"\nquality: {result.draft}")

    claims = unsupported_claims(result.draft, ("accuracy", "time", "publisher"))
    assert not claims, f"unmarked claims: {claims}"

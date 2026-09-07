"""Trim AI tool results before they are echoed back into the model's context.

A chat tool result serves two consumers: the **action collector**, which
forwards map payload (GeoJSON overlays) to the browser, and the **model**,
re-fed the result as conversation context to narrate the outcome.

Geometry is exclusively the collector's business — the model narrates from
``feature_count``/``row_count``/``rows``, never raw coordinates. Left in, a
412-feature ``run_analysis`` preview serialized to ~1.3 MB (~325k tokens),
blowing ``MAX_REQUEST_TOKEN_BUDGET`` in one round.

Call this at every point where a result is serialized *for the provider*;
the action collector must keep receiving the untrimmed dict.
"""

from __future__ import annotations

import json

from app.platform.prompt_fence import (
    TOOL_RESULT_PREAMBLE,
    fence_untrusted_content,
)

# Keys whose whole purpose is client-side map rendering. `bbox` deliberately
# stays: it is four numbers and gives the model useful spatial context.
_MAP_ONLY_KEYS = frozenset({"geojson"})


def model_safe_tool_result(result: dict) -> dict:
    """Return ``result`` without map-only payload, for provider serialization.

    Returns the original object when there is nothing to strip, so the common
    path allocates nothing.
    """
    if not any(key in result for key in _MAP_ONLY_KEYS):
        return result
    return {k: v for k, v in result.items() if k not in _MAP_ONLY_KEYS}


def tool_result_content(result: dict) -> str:
    """Serialize one tool result for the provider, inside the trust fence.

    fix(#1778): catalog tool results carry text nobody on this side
    wrote — `search_datasets`/`get_dataset_details` return other users'
    PUBLIC titles/summaries/keywords, `query_data`/`run_analysis` return raw
    rows, `add_layer` echoes a catalog dataset name. A phrase blacklist is a
    mitigation, not a boundary. The boundary: the model is told, at the
    point of use, that what follows is output, and a forged closing marker
    is stripped so the text cannot step outside the region.

    Every result is fenced, not an enumerated subset — an enumeration rots
    (`add_layer` looks like a pure echo of the model's own input but already
    carries catalog text). The blacklist stays as defence in depth behind
    this.

    default=str: query_data rows can carry Decimal/datetime values straight
    from PostGIS.
    """
    payload = json.dumps(model_safe_tool_result(result), default=str)
    return fence_untrusted_content(payload, preamble=TOOL_RESULT_PREAMBLE)

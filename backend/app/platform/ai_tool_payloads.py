"""Trim AI tool results before they are echoed back into the model's context.

A chat tool result serves two consumers with very different needs:

- the **action collector**, which forwards map payload (GeoJSON overlays) to
  the browser, and
- the **model**, which is re-fed the tool result as conversation context so it
  can narrate the outcome.

Geometry is exclusively the first consumer's business — the model narrates from
``feature_count`` / ``row_count`` / ``rows``, never from raw coordinates. Left
in, a single ``run_analysis`` buffer preview of a 412-feature layer serialized
to ~1.3 MB (~325k tokens), blowing MAX_REQUEST_TOKEN_BUDGET in one round and
billing the user for coordinates the model cannot use. ``query_data``'s overlay
(capped at 50 features) was quietly paying a smaller version of the same tax.

Call this at every point where a tool result is serialized *for the provider*;
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

    fix(#1778 round 2): catalog tool results carry text nobody on this side
    wrote. `search_datasets` returns titles, summaries and keywords from other
    users' PUBLIC datasets; `get_dataset_details` returns the same for any
    dataset the caller can see; `query_data` and `run_analysis` return raw rows
    and column names; `add_layer` echoes a catalog dataset name. Scrubbing
    those fields is a phrase blacklist, and a blacklist is a mitigation, not a
    boundary. The boundary is this: the model is told, at the point of use,
    that what follows is output rather than instruction, and the same pattern
    that guards the system prompt strips a forged closing marker so the text
    cannot step outside the region.

    Every tool result is fenced, not an enumerated subset. An enumeration is a
    list that rots: `add_layer` already carries catalog text while looking like
    a pure echo of the model's own input, and the next tool to grow a title
    field would join it silently. The blacklist stays where it is, as defence
    in depth behind this.

    default=str: query_data rows can carry Decimal / datetime values straight
    from PostGIS.
    """
    payload = json.dumps(model_safe_tool_result(result), default=str)
    return fence_untrusted_content(payload, preamble=TOOL_RESULT_PREAMBLE)

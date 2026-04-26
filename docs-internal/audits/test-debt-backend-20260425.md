---
audit_type: test-debt
audit_date: 2026-04-25
scope: backend pytest suite
status: documented_for_triage
total_failures: 15
suite_size: 1965
pass_rate: 99.24%
---

# Backend Test Debt — 2026-04-25

**Context.** Discovered while running the green-baseline check for the popup_config post-impl audit. These 15 failures predate the popup_config feature and are not introduced by recent work. The popup feature's own tests (101/101 in `test_maps.py` + 30/30 frontend) all pass. Documenting here so they don't keep masking future audits' baselines.

## Failure list

| # | Test | Failure shape | Cluster |
|---|------|---------------|---------|
| 1 | `test_ai_chat.py::test_validate_overwrites_client_table_name` | Assertion | AI chat |
| 2 | `test_ai_chat.py::test_validate_filters_inaccessible_dataset` | Assertion | AI chat |
| 3 | `test_chat_streaming.py::test_stream_returns_sse_events` | Assertion | Chat streaming |
| 4 | `test_chat_streaming.py::test_non_streaming_fallback` | ValueError | Chat streaming |
| 5 | `test_chat_streaming.py::test_tool_progress_events` | `assert 0 >= 1` | Chat streaming |
| 6 | `test_chat_streaming.py::test_query_data_stage_events` | Assertion | Chat streaming |
| 7 | `test_chat_streaming.py::test_show_query_result_action_in_stream` | (no message) | Chat streaming |
| 8 | `test_ogc_collection_metadata.py::test_per_dataset_collection_has_extent_in_list` | Assertion | OGC catalog |
| 9 | `test_ogc_collection_metadata.py::test_per_dataset_collection_has_root_link_in_list` | Assertion | OGC catalog |
| 10 | `test_ogc_features.py::test_collections_includes_dataset_collections` | Assertion | OGC catalog |
| 11 | `test_search.py::test_search_filter_by_date_range` | `assert 0 >= 4` | Search |
| 12 | `test_public_urls.py::test_load_public_url_overrides_unwraps_json_values` | Test pollution (passes alone) | Test pollution |
| 13 | `test_stac_record_output.py::TestStacDatetime::test_datetime_null_when_no_temporal` | `assert '2026-04-26T...Z' is None` | STAC trade-off |
| 14 | `test_stac_record_output.py::TestStacExtensionsRemoved::test_raster_record_no_stac_extensions` | Assertion | STAC compliance |
| 15 | `test_stac_record_output.py::TestStacExtensionsRemoved::test_no_bands_without_band_info` | Assertion | STAC compliance |

## Triage by cluster

### 1. STAC trade-off (1 failure: #13)

`test_datetime_null_when_no_temporal` expects `properties.datetime = null` when a record has no temporal info. The current serializer at `backend/app/modules/catalog/search/service.py:1051-1057` falls back to `record.created_at` "so the item always passes STAC validation." This is intentional behavior, not a regression — see the inline comment.

**Decision needed:** Is the goal pure STAC compliance (datetime can be null with no start/end) or defensive validation pass (always emit a datetime)? Either remove the fallback or update the test assertion.

### 2. STAC compliance (2 failures: #14, #15)

`test_raster_record_no_stac_extensions` and `test_no_bands_without_band_info` check serializer behavior on raster records. Most likely related to the same OGC/STAC compliance audit lineage as #13. Need to inspect actual outputs to distinguish "code is wrong" from "test is wrong."

### 3. AI chat / chat streaming (7 failures: #1-#7)

These are chat workflow tests. Pattern of `assert 0 >= 1` and ValueError suggests fixture or setup is producing zero rows / events when the test expects a populated stream. Could be:
- LLM provider response format change
- DB fixture not seeding chat-eligible datasets
- Test pollution from other tests' state

### 4. OGC catalog (3 failures: #8, #9, #10)

Per-dataset collection extents and root links. Likely a serializer divergence between what the tests assert and what the OGC router emits. Same cluster as #13/#14/#15 (related to OGC/STAC standards work).

### 5. Search (1 failure: #11)

`test_search_filter_by_date_range` expects ≥4 datasets created today to be visible in `date_from=yesterday, date_to=tomorrow`. Getting 0. Either:
- Fixture datasets aren't being created
- `created_at` server default + UTC vs local timezone shift moves "today" outside the filter window

### 6. Test pollution (1 failure: #12)

`test_public_urls.py::test_load_public_url_overrides_unwraps_json_values` **passes when run alone** but fails as part of the full suite. Classic test isolation bug — earlier tests are leaving DB/cache state that breaks this one. Hardest to triage without isolating which tests pollute.

## Recommendations

1. **Quick win:** Frontend equivalent debt (9 `AppLayout.test.tsx` failures) was a single missing mock — fixed in commit `6d72b72a`. The backend doesn't have an equivalent single fix.
2. **Triage cluster 1 + 2 first** (3 failures): one round of decisions about STAC compliance vs validation strictness clears it.
3. **Cluster 6** (test pollution): worth investigating because it makes the suite flaky in CI. Run pytest with `--randomly-seed` or bisect by halving to find the polluter.
4. **Cluster 3 (AI chat)** is the largest. If the tests were written against an older streaming protocol, they may need a sweep alongside the next AI feature work.
5. **Cluster 5** is one test, probably timezone — easy to fix with `freeze_time` or by widening the range.

Until these are addressed, the green-baseline gate in `/post-impl` and similar audits will keep flagging them. Consider marking them `xfail` with a reason string, or moving them to a `tests/known_failing/` directory so the green-bar metric reflects ongoing state accurately.

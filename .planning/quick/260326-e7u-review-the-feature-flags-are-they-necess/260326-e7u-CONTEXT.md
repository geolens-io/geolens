# Quick Task 260326-e7u: Review the feature flags - are they necessary? - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Task Boundary

Review the 5 boolean feature flags (PersistentConfig entries) in the GeoLens backend to assess whether each is necessary. Flags: registration_enabled, ai_enabled, semantic_search_enabled, require_metadata_for_publish, ai_send_sample_values.

</domain>

<decisions>
## Implementation Decisions

### Scope of Review
- Evaluate each flag for value vs. complexity — does it serve a real operational need or is it dead weight / premature abstraction?
- Consider future repo-split (docs/GTM/repo-split.md) — some flags may eventually become enterprise extension points, but that's context, not the primary lens.

### Removal Criteria
- Only recommend removal if a flag is literally unused or duplicates another mechanism.
- Conservative bar — don't recommend removing flags that serve a legitimate deployment scenario.

### Deliverable
- Recommendation doc only — no code changes.
- Analysis with keep/remove/change recommendations for each flag.

### Claude's Discretion
- Doc format and structure
- How deep to trace each flag's usage across frontend/backend

</decisions>

<specifics>
## Specific Ideas

- Cross-reference with repo-split.md extension seam plan (auth, audit, settings/branding, ai policy) to note which flags align with future enterprise patterns
- Check if any flags are never actually read/toggled in practice

</specifics>

<canonical_refs>
## Canonical References

- docs/GTM/repo-split.md — enterprise repo-split strategy, extension seam plan
- backend/app/persistent_config.py — all PersistentConfig declarations
- backend/app/settings/ — settings API surface

</canonical_refs>

---
phase: 260329-lnd
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md
autonomous: true
requirements: [VALIDATE-ALL-5]

must_haves:
  truths:
    - "All 5 review findings have been tested against the live app with Playwright MCP tools"
    - "Each finding has a verdict: confirmed, disputed, or revised"
    - "Severity ratings are independently evaluated, not rubber-stamped"
    - "A standalone validation report exists with per-finding evidence"
  artifacts:
    - path: ".planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md"
      provides: "Standalone validation report with verdicts and evidence"
      min_lines: 80
  key_links: []
---

<objective>
Validate all 5 findings from the search card review (260330-REVIEW.md) by inspecting the live app at http://localhost:8080 using Playwright MCP server tools. Produce a standalone validation report with per-finding verdicts and severity assessments.

Purpose: Independent verification of review claims with live evidence, not just code reading.
Output: 260329-lnd-VALIDATION.md with confirmed/disputed/revised verdicts per finding.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-CONTEXT.md
@.planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-RESEARCH.md
@.planning/quick/260330-review-the-current-state-of-the-search-c/260330-REVIEW.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Inspect all 5 findings with Playwright MCP tools</name>
  <files>.planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md</files>
  <action>
Use Playwright MCP server tools (mcp__playwright__*) to validate each of the 5 review findings against the live app at http://localhost:8080. Do NOT use the existing e2e test infrastructure -- use MCP tools directly.

**Setup:**
1. Use `mcp__playwright__browser_navigate` to open http://localhost:8080
2. Set viewport to 1440x900 for desktop findings

**Finding 1 — Empty state + collection card simultaneously (HIGH):**
1. Navigate to `/search?q=Natural+Earth+Cultural`
2. Wait for results to load
3. Use `mcp__playwright__browser_snapshot` to capture the page state
4. Check if both "No results found" text AND a search result card are visible simultaneously
5. Take a screenshot as evidence
6. Verdict: confirmed if both elements coexist, disputed if only one appears

**Finding 2 — max-w-3xl dead gutter on desktop (MEDIUM-HIGH):**
1. Navigate to a search with dataset results (e.g., `/search?q=land`)
2. Use `mcp__playwright__browser_snapshot` to inspect card layout
3. Use `mcp__playwright__browser_console` with JavaScript to measure:
   - Card total width via `document.querySelector('[data-testid="search-result-card"]').getBoundingClientRect()`
   - Description element width
   - Source element width
4. Calculate the dead gutter between text right edge and preview area
5. Verdict: confirmed if gutter > 100px, evaluate if severity matches

**Finding 3 — Flat information hierarchy, tags heavier than facts (MEDIUM):**
1. On the same search results page, snapshot a card with both specs and tags
2. Use `mcp__playwright__browser_console` to extract computed styles:
   - Font-weight on spec elements vs tag elements
   - Whether tags have border, background-color, padding
   - Whether specs are plain unstyled text
3. Compare visual weight indicators
4. Verdict: confirmed if tags have demonstrably more visual weight (borders, backgrounds, font-medium) than specs

**Finding 4 — Preview failure shows weak fallback (MEDIUM):**
1. Navigate to a search that includes datasets
2. Use `mcp__playwright__browser_snapshot` to look for any cards already showing the ImageOff fallback icon
3. If no natural failures exist, note this and evaluate based on code (the RESEARCH.md already confirmed the code path)
4. Check if any fallback states show text like "Preview unavailable" -- absence confirms the finding
5. Verdict: confirmed if error fallback is icon-only with no descriptive text

**Finding 5 — Collection card is sparse (LOW-MEDIUM):**
1. Navigate to `/search?q=Natural+Earth+Cultural` (should show collection)
2. Snapshot the page and identify collection card(s)
3. Confirm collection cards lack: preview image, specs row, tags row, source org
4. Measure collection card height vs dataset card height (if both visible, or navigate to get both)
5. Evaluate whether the card feels like "dataset card minus sections" vs intentionally designed
6. Verdict: confirmed if collection card renders as a wide sparse block missing dataset-specific bands

**Report:**
After all 5 inspections, write `.planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md` with:

```markdown
# Search Card Review — Playwright Validation Report

**Validated:** {date}
**Review under test:** 260330-REVIEW.md
**Method:** Live Playwright MCP inspection at http://localhost:8080

## Summary

| # | Finding | Review Severity | Validated Severity | Verdict |
|---|---------|----------------|-------------------|---------|
| 1 | ... | HIGH | ... | confirmed/disputed/revised |
| 2 | ... | MEDIUM-HIGH | ... | ... |
| 3 | ... | MEDIUM | ... | ... |
| 4 | ... | MEDIUM | ... | ... |
| 5 | ... | LOW-MEDIUM | ... | ... |

## Finding 1: {title}
### Review Claim
{what the review said}
### Playwright Evidence
{what was observed — DOM state, measurements, screenshots}
### Verdict: {confirmed | disputed | revised}
### Severity Assessment
{agree or disagree with original severity, with reasoning}

... repeat for findings 2-5 ...

## Overall Assessment
{How accurate was the review overall? Any pattern of over/under-rating severity?}
```

Be rigorous. If a finding cannot be reproduced live, say so clearly. If severity seems wrong, explain why and provide a revised rating.
  </action>
  <verify>
    <automated>test -f ".planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md" && grep -c "### Verdict" ".planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-VALIDATION.md" | grep -q "5" && echo "PASS: 5 verdicts found" || echo "FAIL: missing verdicts"</automated>
  </verify>
  <done>Validation report exists with 5 per-finding sections, each containing Playwright evidence, a verdict (confirmed/disputed/revised), and an independent severity assessment. Overall assessment section present.</done>
</task>

</tasks>

<verification>
- 260329-lnd-VALIDATION.md exists and is well-formed
- All 5 findings have verdicts backed by live Playwright evidence
- Severity ratings are independently evaluated, not just echoed from the review
- Overall assessment summarizes agreement/disagreement
</verification>

<success_criteria>
- Standalone validation report with 5 per-finding verdicts
- Each verdict supported by Playwright MCP evidence (DOM snapshots, measurements, console output)
- At least one severity rating is independently evaluated (not all blindly confirmed)
- Overall assessment provides a clear bottom line on the review's accuracy
</success_criteria>

<output>
After completion, create `.planning/quick/260329-lnd-validate-search-card-review-assessment-w/260329-lnd-01-SUMMARY.md`
</output>

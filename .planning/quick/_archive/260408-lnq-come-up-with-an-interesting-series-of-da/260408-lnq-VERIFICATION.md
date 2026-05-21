---
status: passed
checked: 2026-04-08
task: 260408-lnq
score: 8/8 must-haves verified
---

# Verification: 260408-lnq

**Task Goal:** Come up with an interesting series of data for the demo environment and what maps to create with them.
**Artifact:** `.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md`
**Re-verification:** No — initial verification.

---

## Must-Haves Check

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TL;DR covers (a) exactly three themes, (b) automation posture, (c) single largest risk in under 60-second skim | VERIFIED | TL;DR has 5 decisive bullets: three themes named, automation posture stated, ACLED→UCDP and A7 both flagged. Lines 19-25. |
| 2 | Every theme backed by concrete dataset tables with source URL, license, approx size, record_type, and one-line rationale — no TBD | VERIFIED | Three dataset tables (lines 89-133). Each row has source URL, format, size, record_type, license (VERIFIED/ASSUMED noted), and rationale. No "TBD" in any dataset cell confirmed by grep. |
| 3 | Exactly 5-8 signature maps picked, each with named story, layer stack (top→bottom), basemap choice, and 60-second narrative — no menu of options | VERIFIED | 6 maps on the ship list + 4 deferred (clearly conditioned on A7). Each of the 6 ship maps has a detail section with story, basemap, top-to-bottom layer stack, view config, and widgets. Lines 140-207. |
| 4 | Geopolitics safety: explicit ACLED rejection rationale, UCDP substitution, NE disputed-borders policy reference, language-discipline rule | VERIFIED | Dedicated "Geopolitics Safety Notes" section (lines 208-248). Three-EULA-conflict rejection is complete. UCDP substitution documented with CC-BY 4.0 verification. NE policy URL at `naturalearthdata.com/about/disputed-boundaries-policy`. Verbatim language-discipline rule with prohibited words listed. |
| 5 | Automation posture states a single recommendation (automate ingest + collection; fixture maps) with rationale and explicit tradeoffs vs both alternatives | VERIFIED | "Automation Recommendation" section (lines 271-311) states fixture-based as the single pick. Tradeoffs table explicitly rejects "fully automated" and "fully manual" with concrete reasons. |
| 6 | A7 appears in Open Questions with a proposed resolution path; choropleth maps not committed as definitely-shippable | VERIFIED | A7 is item #1 in Open Questions (line 315), flagged "CRITICAL", with a half-day spike resolution path and three fallback options if negative. Maps 2.2 and 3.4 are "ship iff A7 resolves positively" in the signature maps table. |
| 7 | "Suggested Next Steps" closes with a rough phase shape, scope estimate, and sequencing | VERIFIED | 6-plan table with names, scope, prerequisites, and sequencing note (lines 336-359). Scope described as "medium-complexity, ~5-6 plans, 3-4 waves." Decision options (yes/no/not sure) included. |
| 8 | PROPOSAL.md is a distillation (not duplication) of RESEARCH.md — references RESEARCH.md for deep detail | VERIFIED | RESEARCH.md cross-referenced at lines 14-15 and 267. SUMMARY reports 363 lines vs RESEARCH.md's ~430 lines. Proposal uses summary tables rather than copying RESEARCH verbatim; e.g., dataset rationale columns are condensed vs RESEARCH's paragraph form. |

**Score: 8/8**

---

## Context Compliance (CONTEXT.md Locked Decisions)

| Decision | Honored | Evidence |
|----------|---------|----------|
| Strategy doc only — no code changes | Yes | PROPOSAL.md is the only file created. SUMMARY confirms no code, scripts, or fixtures touched. |
| 2-3 themed collections — must recommend exactly 3 | Yes | Exactly three themes recommended. TL;DR line 21 states "exactly three themed collections." |
| Embrace geopolitics carefully — geopolitics IS one of the three themes | Yes | Theme 3 "Borders, Boundaries & Contested Space" is the explicit geopolitics theme. Safety section present. |
| Static snapshots only — no API keys, no runtime outbound internet | Yes | Cache-on-Build Posture section (lines 305-309) states all downloads happen at `Dockerfile RUN` step, not runtime. Copernicus DEM explicitly skipped because it requires login. |

**All 4 locked decisions honored.**

---

## Research Alignment (Critical Findings from RESEARCH.md)

| Finding | Preserved | Evidence |
|---------|-----------|----------|
| ACLED is a landmine — do not ship it | Yes | Explicit ACLED rejection with three-EULA-conflict enumeration (governmental, commercial, AI training). Standing rejection rationale included verbatim for future reviewers. Lines 215-227. |
| UCDP GED v25.1 is the ACLED substitution | Yes | UCDP GED v25.1 in Theme 3 dataset table (line 123). CC-BY 4.0 verified. Conflict Events 2024 map (Map 3.3) on ship list. Full substitution rationale in Safety Notes. |
| A7 (table→polygon join) is unverified | Yes | A7 flagged in TL;DR (line 24), in signature maps table (lines 149-151), and as #1 in Open Questions with CRITICAL label and resolution path (lines 315-322). Maps 2.2 and 3.4 are explicitly conditioned on A7. |
| Fixture-based automation is the recommended approach | Yes | Automation section states fixture approach as accepted, fully automated and fully manual as rejected, with tradeoffs table (lines 297-303). |
| Maps API is automatable but map hand-curation is recommended | Yes | "What Not to Automate: Maps" subsection (lines 286-295) explains the human-validates-once approach with the `_stem` UUID resolution pattern. |

**All 5 critical research findings preserved.**

---

## Artifact Check

| Artifact | Exists | Substantive | Cross-referenced | Status |
|----------|--------|-------------|-----------------|--------|
| `260408-lnq-PROPOSAL.md` | Yes | Yes — 363 lines, 10 required H2 sections all present | Yes — links to CONTEXT.md and RESEARCH.md at top and bottom | VERIFIED |

**Sections confirmed present:** TL;DR, Current State, Recommended Themes, Datasets per Theme, Signature Maps, Geopolitics Safety Notes, Data Sources Catalog, Automation Recommendation, Open Questions & Dependencies, Suggested Next Steps.

---

## Decisiveness Check

The plan required the proposal to be decisive — picks, not menus. Assessment:

- **Themes:** Three named, alternatives documented but rejected with rationale. No ambiguity.
- **Datasets:** Each row is a pick. Skips are documented with hard rationale (too big, login required, wrong license). No "consider X."
- **Maps:** Ship list and deferred list are clearly partitioned. Conditions for deferred maps are concrete (A7 resolution).
- **Automation:** Single recommendation with two explicit rejections.
- **ACLED:** Explicit standing rejection, not "use with caution."

The proposal does not present menus of options — it presents conclusions.

---

## Gaps

None identified.

---

## Recommendation

Pass. The PROPOSAL.md fully achieves the task goal. A reader opening the document can:

1. Read the TL;DR and know the three themes, automation posture, and the one risk that could change scope — in under 60 seconds.
2. Use the dataset tables to begin license audit and download planning with no further research needed for the core datasets.
3. Hand the signature maps section to a map builder and get six maps with unambiguous layer stacks.
4. Use the Open Questions section as a pre-planning checklist, with A7 correctly elevated as the first act.
5. Use the Suggested Next Steps phase sketch to initiate implementation planning immediately.

The document is ready for project owner review and a go/no-go decision on scheduling the implementation phase.

---

_Verified: 2026-04-08_
_Verifier: Claude (gsd-verifier)_

---
phase: 260408-lnq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md
autonomous: true
requirements:
  - LNQ-01-strategy-doc-only
  - LNQ-02-2-to-3-themed-collections
  - LNQ-03-geopolitics-embraced-safely
  - LNQ-04-static-snapshot-sources
  - LNQ-05-automation-posture-recommendation
  - LNQ-06-ship-or-skip-decisiveness
tags:
  - demo
  - content-strategy
  - docs

must_haves:
  truths:
    - "A reader who opens PROPOSAL.md can read the TL;DR in under 60 seconds and walk away knowing (a) exactly three recommended themes, (b) the automation posture (automate ingest, fixture-based maps), (c) the single largest risk (ACLED-not-usable and A7 table-join unverified)."
    - "Every theme recommended in the body is backed by concrete datasets listed with source URL, license, approximate size, GeoLens record_type, and a one-line rationale — no 'TBD' or 'consider X' in the final datasets tables."
    - "The proposal picks exactly 5-8 signature maps across the three themes, each with a named story, layer stack (top→bottom), basemap choice, and the 60-second narrative it tells. No menu-of-options — each map is a decided recommendation."
    - "Geopolitics safety is addressed with an explicit ACLED rejection rationale, the UCDP substitution, the Natural Earth disputed-borders policy reference, and a language-discipline rule for layer descriptions — so a reviewer cannot miss why UCDP is in and ACLED is out."
    - "The automation posture section states a single recommendation (automate dataset ingest + collection assignment; hand-curate maps as JSON fixtures) with the rationale and explicit tradeoffs against the two alternatives (fully automated, fully manual)."
    - "Every item from the RESEARCH Open Questions list that blocks implementation — especially A7 (table→polygon join capability) — appears in the proposal's Open Questions & Dependencies section with a proposed resolution path, so a follow-up phase planner knows exactly what to verify first."
    - "The proposal closes with a concrete 'Suggested Next Steps' section that sketches a rough phase shape, scope estimate, and sequencing a human can use to decide whether/when to schedule the implementation phase."
    - "The final PROPOSAL.md is a distillation, not a duplication, of RESEARCH.md — it is meaningfully shorter and executive-readable, references RESEARCH.md for deep detail, and does not copy verbatim the research tables when a crisper summary works."
  artifacts:
    - path: ".planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md"
      provides: "The polished strategy document"
      contains_sections:
        - "TL;DR"
        - "Current State"
        - "Recommended Themes"
        - "Datasets per Theme"
        - "Signature Maps"
        - "Geopolitics Safety Notes"
        - "Data Sources Catalog"
        - "Automation Recommendation"
        - "Open Questions & Dependencies"
        - "Suggested Next Steps"
  key_links:
    - from: ".planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md"
      to: ".planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-RESEARCH.md"
      via: "explicit cross-reference link near the top"
      pattern: "260408-lnq-RESEARCH.md"
    - from: ".planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md"
      to: ".planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-CONTEXT.md"
      via: "constraints acknowledgement near the top"
      pattern: "260408-lnq-CONTEXT.md"
---

<objective>
Distill the research findings in `260408-lnq-RESEARCH.md` into a polished, decisive, executive-readable strategy document (`260408-lnq-PROPOSAL.md`) that lets the project owner decide whether and when to schedule an implementation phase for a themed demo environment.

Purpose: The research explored the full solution space (six themes, thirteen datasets per theme, eight open questions, three automation postures). A human decision-maker does not have time to read all of it. The proposal is the 10-minute version that picks winners, flags the real risks (ACLED, A7 table-join), and proposes a phase shape.

Output: A single markdown file at `.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md`. No code. No other files touched.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-CONTEXT.md
@.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-RESEARCH.md

<!-- Reference files — do NOT duplicate. The proposal distills from these. -->
<!-- CONTEXT.md = locked user decisions. RESEARCH.md = verified source material. -->

<constraints>
- **Doc-only task.** The only file created is `260408-lnq-PROPOSAL.md`. Do not create, modify, or touch any code, scripts, fixtures, or other planning files.
- **Distillation, not duplication.** The RESEARCH.md is ~430 lines. The PROPOSAL.md should be meaningfully shorter — target 400-600 lines of polished prose plus tables, not a re-typing of the research. Reference RESEARCH.md for anyone who wants the deep detail.
- **Decisive, not a menu.** Every theme, every dataset, every map, every automation decision is a pick — not "option A or option B." The research already did the tradeoff analysis; the proposal states the conclusion.
- **Honor locked CONTEXT.md decisions exactly:**
  - Strategy doc only (already satisfied by this very task)
  - 2-3 themed collections — the proposal MUST recommend exactly 3
  - Embrace geopolitics carefully — geopolitics IS one of the three themes, with safety discipline
  - Static snapshots only — no datasets that require live API calls or API keys in the baseline
- **Honor the critical research findings:**
  - ACLED is not usable — the proposal MUST explicitly reject ACLED and substitute UCDP GED, with rationale a reviewer can repeat back verbatim
  - A7 (table-to-polygon join capability) is unverified — the proposal MUST flag this in Open Questions & Dependencies with a proposed resolution path, and must NOT commit to the "GDP per Capita choropleth" signature map as definitely-shippable without a verification step
- **No git commits inside this task.** The orchestrator commits at the end. The executor writes the file and nothing else.
- **Tone discipline.** Direct, concrete, no marketing language. A reader should be able to skim and know what to do next.
</constraints>

<reference_file_summary>
<!-- Key facts the executor must preserve when distilling. This is the "must-include" list. -->

**Three recommended themes (from RESEARCH §Summary):**
1. **Planet Earth: Physical Systems** — exercises vector + raster COG + VRT mosaic. Signature story: "Earth as seen from space." Key datasets: Natural Earth 10m baseline (reuse), Natural Earth shaded relief COG, GEBCO bathymetry COG (downsampled ~200MB), Natural Earth 10m raster mosaic as a VRT.
2. **Global Development & People** — exercises vector + table records + semantic search. Signature story: "How the world lives." Key datasets: World Bank WDI CSVs (population, GDP/cap PPP, life expectancy, internet penetration, urban share, under-5 mortality), Our World in Data CSVs (HDI, GINI, V-Dem democracy), SEDAC Gridded Population of the World v4 (coarse COG).
3. **Borders, Boundaries & Contested Space** — the geopolitics theme, done safely. Signature story: "One territory, multiple official maps" (the parallel NE country views of Kashmir). Key datasets: Natural Earth disputed_areas, breakaway_disputed, boundary_lines_disputed, the nine country-specific ne_10m_admin_0_countries_{arg,chn,ind,isr,pak,rus,tur,ukr,usa} shapefiles (already in baseline manifest, just unused), UCDP GED v25.1 (2015-2024 subset), UNHCR refugee statistics, UN/NATO/EU/BRICS treaty-membership CSV (hand-curated from World Factbook).

**Hard rejects with rationale:**
- **ACLED** — EULA restricts governmental, commercial, and AI training use. GeoLens targets gov buyers, has AI chat, is commercial/open-core. Three-way EULA conflict. Use UCDP GED instead (CC-BY 4.0, no AI restriction, verified).
- **GADM** — license is not a true open license, prohibits some commercial redistribution. Use Natural Earth admin_0_countries instead.
- **Freedom House** — license terms unclear, interpretive ratings politically charged. Skip.
- **Marine Regions EEZ** — CC-BY 4.0 but disputed maritime boundaries add a second sensitivity surface. Defer.

**Signature maps — pick these (5-8 total, decisive):**
- Theme 1: "Earth as Seen from Space" (Map 1.1, 60-sec signature), "Global Bathymetry" (Map 1.2, COG showcase), "Where the Ice Is" (Map 1.3, focused story)
- Theme 2: "Population at a Glance" (Map 2.1, 60-sec signature, AI-built from prompt), "GDP per Capita PPP 2023" (Map 2.2, choropleth + A7-dependent — flag with dependency), "Life Expectancy & Income" (Map 2.3, two-variable outlier story — deferrable)
- Theme 3: "The World's Disputed Places" (Map 3.1, 60-sec signature), "One Territory, Multiple Official Maps" (Map 3.2, **the** conversation-starter), "Conflict Events 2024 (UCDP GED)" (Map 3.3, point density), "Refugees by Country of Origin 2023" (Map 3.4, also A7-dependent — flag)

The proposal should pick 5-8 of these as "ship list" and clearly mark which ones depend on A7 resolution. Recommended ship list: Maps 1.1, 1.2, 2.1, 3.1, 3.2, 3.3 as A7-independent (6 maps, decisive). Maps 1.3, 2.2, 2.3, 3.4 as "add if A7 resolves / if time permits." That's the decisiveness posture.

**Automation posture (from RESEARCH §Automation Posture):**
- Automate: vector ingest, raster COG ingest, VRT mosaic creation, table (CSV) record ingest, collection creation, collection-to-dataset assignment. All of these reuse primitives from `seed-natural-earth.py`.
- Do NOT automate from code: sample map creation. Use JSON fixtures: human builds a signature map once in the UI, exports via `GET /api/maps/{id}`, commits to `scripts/fixtures/demo-maps/*.json`. Seeder re-reads fixture, rewrites `layers[].dataset_id` by name lookup (pattern exists in `fetch_existing_datasets`), and PUTs to the map API.
- Do NOT automate: share token minting (security surface, operator opt-in).
- **Why fixtures:** maps have ~30 style knobs per layer; hand-coding in Python is verbose, fragile against schema changes, and divergent from what humans build in the UI. Fixtures let humans validate once and re-seed deterministically. The fixture approach is the recommendation.
- **Cache-on-build:** downloads happen at seeder container build time (Dockerfile RUN), not at run time, satisfying the "no outbound internet at demo run-time" constraint.
- Total disk budget: ~1.2-1.5 GB bundled, ~3 GB after ingest. GEBCO is the dominant cost — downsample further if the budget is tight.

**Critical open questions for the implementation phase (from RESEARCH §Open Questions, distilled):**
- **A7 — Table→polygon join capability.** CRITICAL. Determines whether Theme 2's signature choropleth map and Theme 3's refugee map ship. Resolution path: quick spike against `backend/app/maps/service.py` and the AI map builder code in a half-day investigation. If the join exists, Maps 2.2 and 3.4 ship as designed. If it does not, either (a) pre-materialize GeoJSON views that carry the joined attributes, (b) ship without the table-joined maps and cover the "table record" capability demonstration with semantic-search and facet UX instead, or (c) build the join capability as part of the implementation phase itself.
- VRT mosaic count — one is enough to demonstrate the feature; ship one.
- Share link posture — default off, operator opts in.
- reset-demo.sh scope — the thematic seeder must be idempotent and scoped to the demo's own datasets/collections/maps; review `scripts/reset-demo.sh` before writing the new seeder.
- i18n of layer titles/descriptions — English-only for the baseline demo; translation deferred.
- AI chat suggested prompts — nice-to-have, schedule as a stretch goal in the implementation phase.
- STAC 1.1 metadata for raster datasets — include in the raster ingest bodies so the STAC export feature is demonstrable.
- Refresh cadence ownership — define in the implementation phase; target annual refresh gated on a "snapshot date > N days old" check in CI.

**Suggested implementation phase shape (for Suggested Next Steps section):**
A follow-up phase to implement this proposal would be roughly:
- **Plan 1 (foundation):** A7 verification spike + `scripts/seed-thematic-demo.py` skeleton that extends `seed-natural-earth.py` primitives. ~15-25% context.
- **Plan 2 (Theme 1 — Planet Earth):** Ingest pipeline for Natural Earth shaded relief COG, GEBCO bathymetry COG, VRT mosaic creation, collection assignment. Build + export fixtures for Maps 1.1, 1.2, 1.3. ~20-30% context.
- **Plan 3 (Theme 2 — Development & People):** World Bank + OWID + SEDAC ingest, Map 2.1 (always ships), Maps 2.2/2.3 conditional on A7 outcome. ~20-30% context.
- **Plan 4 (Theme 3 — Borders & Contested Space):** Enable the nine country-specific NE shapefiles already in the baseline manifest, ingest UCDP GED + UNHCR + treaty CSV, build + export fixtures for Maps 3.1, 3.2, 3.3. ~20-30% context.
- **Plan 5 (wiring):** Dockerfile build-time dataset caching, `seed-demo.sh` integration, `reset-demo.sh` scope updates, README update. ~15% context.
- **Plan 6 (verification checkpoint):** Human verifies the three collections render end-to-end and each signature map tells its 60-second story. ~10%.

Rough total: 5-6 plans across 3-4 waves. Medium-complexity implementation phase. Estimated scope similar to v12.3 Map Builder Excellence (6 plans).

</reference_file_summary>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Draft PROPOSAL.md — TL;DR, current state, recommended themes, and datasets</name>
  <files>.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md</files>
  <action>
Create the file `260408-lnq-PROPOSAL.md` at the path above. Do not read or modify any other files. The file must start with YAML frontmatter and include, in order:

1. **Frontmatter** (4-6 lines):
   ```yaml
   ---
   title: "Demo Environment Data & Maps — Strategy Proposal"
   quick_id: 260408-lnq
   date: 2026-04-08
   status: proposal
   decision_required_from: project owner
   ---
   ```

2. **Title + one-line positioning sentence.** Example: "A decision document for whether and when to ship themed demo content (three collections, six signature maps) to replace the current reference-layer-only demo."

3. **Links to reference files.** Two lines: link to `260408-lnq-CONTEXT.md` ("locked decisions this proposal honors") and `260408-lnq-RESEARCH.md` ("source material — full dataset tables, API verifications, safety analysis"). Tell the reader: read this proposal for decisions, read the research for the evidence behind them.

4. **TL;DR** — exactly 5 bullets, each one sentence, each decisive. Must include:
   - The three recommended themes by name
   - The automation posture (automate data ingest + collection assignment; hand-curate signature maps as JSON fixtures)
   - The ACLED rejection + UCDP substitution in one line
   - The A7 (table→polygon join) risk as the one thing that could reshape scope
   - The suggested next step (schedule a ~5-plan implementation phase)

5. **Current State** — a short section (~150-250 words) covering:
   - What the demo looks like today: `scripts/seed-demo.sh` seeds ~20 Natural Earth reference layers, no maps, no narrative, no showcase of raster/VRT/table/AI-builder/Collections features. Cite the concrete scripts: `seed-demo.sh`, `seed-natural-earth.py`.
   - Why this matters: the platform works, but a prospective user opening the demo sees a catalog of technical reference layers, not a story about what GeoLens is for.
   - The opportunity: themed collections let the platform showcase breadth of capability (every record type exercised, Collections feature used as designed) while telling a memorable story in three cognitive modes.

6. **Recommended Themes** — a short introduction sentence, then three H3 sections, one per theme. For each theme include:
   - **Elevator pitch** (1-2 sentences, memorable)
   - **Collection name** (the exact name that will appear in the GeoLens UI)
   - **Why this theme** (2-3 sentences: what capabilities it exercises, what story it tells, why it belongs in the final three)
   - **Record types exercised** (a single clear line, e.g., "vector + raster COG + VRT mosaic")
   - **Signature 60-second story** (one sentence: the first-impression screen a prospect sees)

   The three themes are fixed: Planet Earth — Physical Systems; Global Development & People; Borders, Boundaries & Contested Space. Do not propose alternatives in this section; alternatives belong in a one-liner at the end of the section ("Backup themes considered and rejected: Climate & Disaster, Energy & Infrastructure, Culture & History — see RESEARCH §Candidate Themes.").

7. **Datasets per Theme** — three tables, one per theme. Each table row must include: dataset name, source, format, approximate size, GeoLens record_type, license, and a one-line "why this one" rationale. Keep the tables tight — only include datasets the proposal is actually recommending. Explicit skips (GADM, ACLED, Marine Regions EEZ, OSM global extracts) go in a "Skips, with rationale" bullet list immediately after the three tables, NOT as table rows.

   Use the exact dataset list from `<reference_file_summary>` above. Do not add new datasets. Do not drop datasets. Each theme should show 4-7 dataset rows.

**Writing discipline for this task:**
- Direct, concrete language. No marketing prose ("revolutionary," "stunning," "unparalleled").
- No "TBD" or "consider X" in this half of the document — every item is a pick.
- Reference the research (`260408-lnq-RESEARCH.md §{section}`) for readers who want more detail, don't copy research tables verbatim when a tighter summary works.
- Use tables for anything that would otherwise be a bulleted list of 4+ items with 3+ attributes.
- Target ~200-350 lines for the sections covered by this task (frontmatter through Datasets per Theme).

**Do not write the Signature Maps section, Safety Notes, Data Sources Catalog, Automation Recommendation, Open Questions, or Suggested Next Steps in this task.** Task 2 completes those. End this task with a clear "<!-- TASK 2 CONTINUES BELOW -->" HTML comment at the end of the file so the next task knows exactly where to append.
  </action>
  <verify>
    <automated>test -f .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "TL;DR" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Planet Earth" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Global Development" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Borders" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "UCDP" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "TASK 2 CONTINUES BELOW" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md</automated>
  </verify>
  <done>
`260408-lnq-PROPOSAL.md` exists with frontmatter, TL;DR (5 decisive bullets), Current State, Recommended Themes (exactly 3: Planet Earth, Global Development & People, Borders), and Datasets per Theme (3 tables with concrete dataset rows). ACLED/GADM/Freedom House/EEZ skips listed with rationale. Research file is referenced, not duplicated. "TASK 2 CONTINUES BELOW" marker present at end of file.
  </done>
</task>

<task type="auto">
  <name>Task 2: Complete PROPOSAL.md — maps, safety, sources catalog, automation, open questions, next steps</name>
  <files>.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md</files>
  <action>
Read the file from Task 1 to confirm it ends with the "<!-- TASK 2 CONTINUES BELOW -->" marker. Replace that marker with the remaining six sections, in this exact order:

1. **Signature Maps** — introduce with one sentence ("Six maps across the three themes, chosen to tell a 60-second story on first load and reward exploration afterward."), then a compact decision table:

   | # | Theme | Name | 60-sec story | A7-dependent? | Ship list |
   |---|---|---|---|---|---|
   | 1.1 | Planet Earth | Earth as Seen from Space | ... | no | **ship** |
   | 1.2 | Planet Earth | Global Bathymetry | ... | no | **ship** |
   | 2.1 | Development & People | Population at a Glance | ... | no | **ship** |
   | 3.1 | Borders | The World's Disputed Places | ... | no | **ship** |
   | 3.2 | Borders | One Territory, Multiple Official Maps | ... | no | **ship** (the conversation starter) |
   | 3.3 | Borders | Conflict Events 2024 (UCDP GED) | ... | no | **ship** |
   | 1.3 | Planet Earth | Where the Ice Is | ... | no | add if time permits |
   | 2.2 | Development & People | GDP per Capita PPP 2023 | ... | **yes — A7 critical** | ship iff A7 resolves positively |
   | 2.3 | Development & People | Life Expectancy & Income (outliers) | ... | partial — depends on join approach | add if A7 resolves |
   | 3.4 | Borders | Refugees by Country of Origin 2023 | ... | **yes — A7 critical** | ship iff A7 resolves positively |

   After the table, include a **Map detail blocks** subsection with H4 entries for each of the 6 "ship" maps only. Each block has: Story (1 sentence), Basemap, Layers top→bottom (compact list), View (center/zoom if known), Widgets, and a one-line "Why this map matters" if it's Map 3.2 (the conversation starter deserves the explicit callout). Do NOT re-detail the deferred maps — the table is enough for them.

2. **Geopolitics Safety Notes** — a tight section (~250-400 words) covering:
   - **The two tests:** every geopolitics dataset must pass (1) license test — commercial + governmental + AI use compatible — and (2) editorial test — source has a published policy for contested claims.
   - **The ACLED decision, with rationale in reviewer-repeatable form:** three EULA conflicts — ACLED prohibits governmental use without paid license, ACLED prohibits commercial use without paid license, ACLED prohibits AI training. GeoLens targets government buyers, is commercial/open-core, and has an AI chat feature. Three-for-three conflict. Cite `acleddata.com/eula`. **Use UCDP GED instead** — same subject matter (organized violence events), CC-BY 4.0, no AI restriction, peer-reviewed academic source, published codebook.
   - **The Natural Earth disputed-borders policy.** NE has had a published disputed-boundaries policy since 2009. GeoLens renders what NE says; disputes with NE's framing go to NE, not GeoLens. Cite `naturalearthdata.com/about/disputed-boundaries-policy`.
   - **Language discipline rule for layer descriptions:** reproduce the pattern from RESEARCH exactly: "Source: {Source} v{version}, released {date}. {Source}'s published policy on contested regions: {URL}. Contents shown per {Source}'s editorial stance, not GeoLens."
   - **Hard no-go list:** ACLED, Freedom House (license uncertain), any single-country partisan source, any layer whose metadata uses words like "aggression"/"occupation"/"terrorism" except as verbatim quotes from the source.

3. **Data Sources Catalog** — a single consolidated table with columns: Source, Provider, License, URL, Themes used in, Verification status. Every source mentioned in the three theme dataset tables must appear here exactly once. Include verification markers (VERIFIED / ASSUMED) matching how RESEARCH.md labels them. This is the one place where a reviewer can audit license posture without reading the whole document.

4. **Automation Recommendation** — ~250-400 words. State the recommendation in the first sentence: "Automate dataset ingest, raster/VRT processing, and collection assignment. Hand-curate signature maps as JSON fixtures committed to the repo." Then cover:
   - **What to automate** — bullet list with a one-line justification per item (vector ingest, raster COG ingest with `gdal_translate -of COG` at build time, VRT creation, table CSV ingest, collection creation, collection→dataset assignment). Mention that every primitive already exists in `seed-natural-earth.py` and the new seeder extends it, not replaces it.
   - **What to NOT automate from code: maps.** Maps have ~30 style knobs per layer. Hand-coding in Python is verbose, fragile against schema changes, and divergent from what humans build in the UI. Use fixtures instead: human builds map once in UI, exports via `GET /api/maps/{id}`, commits JSON, seeder re-reads and PUTs. The one hard part (dataset UUIDs changing on every seed) is solved by looking up by source filename stem, a pattern already in `fetch_existing_datasets`.
   - **Tradeoffs considered:** briefly contrast with (a) fully-automated Python-generated maps — rejected, schema drift risk, and (b) fully-manual "operator builds maps by hand after seed" — rejected, not reproducible, defeats the demo's determinism goal.
   - **Cache-on-build posture** — downloads happen at seeder container build time (Dockerfile RUN), not at demo run time. Satisfies CONTEXT's "no outbound internet at demo run-time" constraint.
   - **Budget:** ~1.2-1.5 GB bundled, ~3 GB ingested. GEBCO bathymetry is the largest single cost at ~200 MB after downsampling; downsample harder if the bundled budget matters more than the visual.
   - **Share tokens:** NOT automated. Operators opt in. Default off keeps demo secure.

5. **Open Questions & Dependencies** — a numbered list, with each item in "Question → Resolution path → Impact if unresolved" format. Must include:
   1. **A7 — Table→polygon join in map builder.** CRITICAL. Resolution: half-day spike against `backend/app/maps/service.py` and the AI map builder tool code — verify whether a `record_type=table` CSV can join to an ADM0 polygon on ISO3 and produce a choropleth fill. Impact: determines whether Maps 2.2 and 3.4 ship as designed, or require pre-materialized GeoJSON, or defer to a future phase. **This is the one dependency that could reshape the implementation phase.**
   2. VRT mosaic count — one is enough for the demo; ship exactly one in Theme 1.
   3. Share link posture — default off; operator opts in.
   4. `reset-demo.sh` scope — the new seeder must be idempotent and scoped to its own datasets; review the reset script as the first step of the implementation phase.
   5. i18n of layer titles/descriptions — English-only for baseline; translation deferred.
   6. AI chat seeded prompts — nice-to-have, schedule as a stretch goal.
   7. STAC 1.1 metadata — include in raster ingest bodies so the STAC export feature is demonstrable.
   8. Refresh cadence — define in the implementation phase; target annual refresh, gated by a "snapshot date > N days old" CI check.

6. **Suggested Next Steps** — close the document with a concrete phase sketch a human can take to `/gsd-discuss-phase`. Include:
   - **Recommendation sentence:** "Schedule this as a medium-complexity implementation phase, roughly the scope of v12.3 Map Builder Excellence (6 plans)."
   - **Rough phase shape** — 5-6 plans, sketched from the `<reference_file_summary>` list in the plan: Foundation + A7 spike → Theme 1 → Theme 2 → Theme 3 → Wiring → Verification checkpoint.
   - **Sequencing note:** Plan 1 MUST complete first because A7 verification gates Theme 2 scope. Themes 1 and 3 are A7-independent and can run in parallel waves after Plan 1.
   - **What to do before scheduling:** run A7 spike as a quick task if you want the uncertainty resolved before planning (~half a day). Otherwise absorb it into Plan 1 of the implementation phase.
   - **Decision the reader makes at the bottom:** "If yes → `/gsd-discuss-phase` with this proposal as the starting context. If no → update STATE.md with the deferred decision so it's visible in the next planning session."

**Writing discipline for this task:**
- Keep the same direct, decisive tone as Task 1.
- Use tables and tight bullet lists, not long prose.
- Every reference to RESEARCH.md details that are too long to inline should be a "see RESEARCH §{section}" pointer, not a duplication.
- Total file length target (Task 1 + Task 2 combined): 400-600 lines. If Task 1's output was longer than that on its own, compress this task's content to stay within budget.
- End the file with a single horizontal rule and a footer line: `*Proposal compiled 2026-04-08 from RESEARCH.md and CONTEXT.md. Source material: `260408-lnq-RESEARCH.md`.*`
- Remove the "<!-- TASK 2 CONTINUES BELOW -->" marker entirely — it must not appear in the final document.

**Self-check before finishing:**
- Does the TL;DR still match the body? (If the body shifted anything, update the TL;DR.)
- Does every section header in `<expected_proposal_structure>` from the plan appear in the file, in order? (TL;DR, Current State, Recommended Themes, Datasets per Theme, Signature Maps, Geopolitics Safety Notes, Data Sources Catalog, Automation Recommendation, Open Questions & Dependencies, Suggested Next Steps.)
- Does the ACLED rejection appear twice (once in TL;DR, once in Safety Notes) and nowhere else — so it's impossible to miss but not over-repeated?
- Is A7 called out as the single biggest risk in TL;DR, in the map ship-list table, and in Open Questions — three touchpoints, not more?
- Does the file reference `260408-lnq-RESEARCH.md` explicitly at least twice (once at the top, once in Data Sources)? If not, add the pointers.
- Is the file free of the "TASK 2 CONTINUES BELOW" marker?
  </action>
  <verify>
    <automated>test -f .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && ! grep -q "TASK 2 CONTINUES BELOW" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Signature Maps" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Geopolitics Safety" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Data Sources Catalog" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Automation Recommendation" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Open Questions" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "Suggested Next Steps" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "A7" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "fixture" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && grep -q "One Territory" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md && [ "$(wc -l < .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md)" -ge 300 ]</automated>
  </verify>
  <done>
`260408-lnq-PROPOSAL.md` is complete end-to-end. All ten expected sections present in order. Signature Maps table lists 6 ship + 4 deferred with A7 dependency flagged. Safety Notes explicitly rejects ACLED with three-EULA-conflict rationale and substitutes UCDP. Data Sources Catalog consolidates every source with license + verification status. Automation recommendation is decisive (automate data, fixture-based maps). Open Questions calls out A7 as the critical dependency. Suggested Next Steps sketches a concrete ~5-plan implementation phase with sequencing notes. The "TASK 2 CONTINUES BELOW" marker is gone. File references RESEARCH.md and CONTEXT.md near the top. Total length 400-600 lines of polished, decisive, executive-readable prose.
  </done>
</task>

</tasks>

<verification>
After both tasks complete, verify the document holistically:

1. `test -f .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md` — file exists
2. All ten expected sections present: `grep -c "^## " .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md` should return a count matching the section heading style used (>=10 for H2 headings, or adjust grep to the actual heading level used).
3. ACLED mentioned exactly in TL;DR and Safety Notes: `grep -c "ACLED" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md` should return 2-5 (not 0, not 20).
4. A7 flagged: `grep -c "A7" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md` should return 3-5 (TL;DR, map ship-list, open questions, maybe automation/suggested next steps).
5. Research reference present: `grep -c "260408-lnq-RESEARCH" .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-PROPOSAL.md` should return >=2.
6. File length reasonable: `wc -l` returns 300-700 lines (distillation, not duplication).
7. No accidental code files created: `ls .planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/` should show exactly three files — CONTEXT.md, RESEARCH.md, PLAN.md, PROPOSAL.md (four once this plan executes).
</verification>

<success_criteria>
- [ ] `260408-lnq-PROPOSAL.md` exists at the target path, and is the only new file.
- [ ] Frontmatter present with title, quick_id, date, status, decision_required_from.
- [ ] TL;DR has exactly 5 decisive bullets covering themes, automation, ACLED→UCDP, A7 risk, next step.
- [ ] Current State section explains the baseline, why it matters, and the opportunity.
- [ ] Exactly 3 recommended themes (Planet Earth, Global Development & People, Borders) with elevator pitches, collection names, record types, signature stories.
- [ ] Three dataset tables (one per theme) with every row showing source, format, size, record_type, license, rationale. Skips (ACLED, GADM, Freedom House, EEZ) listed with reasons.
- [ ] Signature Maps table lists 6 ship maps + 4 deferred, with A7 dependency clearly marked on Maps 2.2 and 3.4.
- [ ] Detail blocks present for the 6 ship maps (story, basemap, layers, view, widgets).
- [ ] Geopolitics Safety Notes explicitly rejects ACLED with three-EULA-conflict rationale, substitutes UCDP, cites Natural Earth disputed-borders policy, includes the language-discipline rule.
- [ ] Data Sources Catalog consolidates every source with license + verification status in a single audit-friendly table.
- [ ] Automation Recommendation is decisive: automate data + collections, fixture-based maps, no automated share tokens. Rationale and tradeoffs covered.
- [ ] Open Questions & Dependencies numbered list, with A7 as #1 and the "critical" flag.
- [ ] Suggested Next Steps sketches a 5-6 plan implementation phase with sequencing notes (Plan 1 gates A7; Themes 1 and 3 can parallelize).
- [ ] File references `260408-lnq-RESEARCH.md` and `260408-lnq-CONTEXT.md` at the top, references RESEARCH.md for deep detail throughout, does NOT duplicate research tables verbatim.
- [ ] Total file length 400-600 lines of polished, executive-readable prose.
- [ ] No "TASK 2 CONTINUES BELOW" marker remains.
- [ ] No code, scripts, fixtures, or other files touched.
- [ ] No git commits inside tasks (orchestrator handles the commit).
</success_criteria>

<output>
After completion, the orchestrator will create `.planning/quick/260408-lnq-come-up-with-an-interesting-series-of-da/260408-lnq-SUMMARY.md` as part of the quick task close-out. This plan's executor does NOT create the SUMMARY — only the PROPOSAL.md.
</output>

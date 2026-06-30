# Starter Issues

A backlog of contribution-ready tickets to help new contributors get started.
Maintainers turn these into tracked issues as capacity allows. If you'd like to
pick one up, open a Discussion or comment on the corresponding issue once it's
filed.

New to the project? Start with the [Contributing guide](./CONTRIBUTING.md).

Each entry lists the area label, the files most likely involved, acceptance
criteria, a test command, and whether the design is settled. **Design-settled**
means the desired behavior is already agreed and you can start coding; otherwise
discuss the approach first.

## Good first issues

### 1. Document the migrate-container exit in the quickstart
- **Area:** docs
- **Files likely involved:** `.github/CONTRIBUTING.md`
- **Acceptance criteria:** A short troubleshooting subsection explains that the
  `migrate` service is expected to exit after it finishes (it is not a crash),
  and how to read its logs with `docker compose logs migrate`.
- **Test command:** n/a (docs) — proofread rendered Markdown.
- **Design settled:** yes

### 2. Add a README package-smoke snippet
- **Area:** docs
- **Files likely involved:** `README.md`, `.github/CONTRIBUTING.md`
- **Acceptance criteria:** The docs show a short clean-environment smoke for
  `pip install geolens geolens-cli` and `npm install @geolens/sdk`.
- **Test command:** n/a (docs).
- **Design settled:** yes

### 3. Add an SDK example for listing datasets
- **Area:** SDK
- **Files likely involved:** `sdks/python/README.md`,
  `sdks/typescript/README.md`
- **Acceptance criteria:** Each SDK README includes a minimal authenticated
  example for listing datasets from a running GeoLens instance.
- **Test command:** n/a (docs).
- **Design settled:** yes

### 4. Document the `&cols=` opt-in for low-zoom vector tiles
- **Area:** spatial-interop
- **Files likely involved:** `README.md` (or a docs pointer)
- **Acceptance criteria:** A short note explains that attribute columns are
  stripped below zoom 10 and that callers can append `&cols=<col>` to request
  specific columns at low zoom.
- **Test command:** n/a (docs).
- **Design settled:** yes

### 5. Add an `.env.example` comment for generated admin credentials
- **Area:** docs
- **Files likely involved:** `.env.example`
- **Acceptance criteria:** The generated admin password behavior is documented
  inline with a reminder to use a strong explicit value before any non-local use.
- **Test command:** n/a (docs).
- **Design settled:** yes

### 6. Add a single-test-file example to the test docs
- **Area:** docs
- **Files likely involved:** `.github/CONTRIBUTING.md`
- **Acceptance criteria:** The "Running tests" section shows how to run one
  backend test file, e.g. `docker compose exec api pytest backend/tests/test_auth.py`.
- **Test command:** n/a (docs) — verify the command runs.
- **Design settled:** yes

### 7. Show a friendlier empty state on the admin shared-maps page
- **Area:** frontend
- **Files likely involved:** `frontend/src/pages/admin/AdminSharedMapsPage.tsx`
- **Acceptance criteria:** When there are no shared maps, the page renders a
  clear empty-state message instead of a blank table.
- **Test command:** `docker compose exec frontend npm test`
- **Design settled:** yes

## Help wanted

These are larger or less settled. Please discuss the approach before starting.

### 8. Improve error messages for unsupported upload formats
- **Area:** backend
- **Files likely involved:** `backend/app/` ingestion handlers, `backend/tests/`
- **Acceptance criteria:** Uploading an unsupported file format returns a clear,
  actionable error naming the accepted formats rather than a generic 400/500.
- **Test command:** `docker compose exec api pytest -k ingest`
- **Design settled:** no — agree the exact message and accepted-format list first.

### 9. Add keyboard navigation to the layer stack
- **Area:** frontend
- **Files likely involved:** Map Builder layer-stack components under
  `frontend/src/`
- **Acceptance criteria:** Layers in the builder stack can be reordered with the
  keyboard, not only by drag-and-drop, with accessible focus handling.
- **Test command:** `docker compose exec frontend npm test`
- **Design settled:** no — discuss the interaction model first.

### 10. Document additional vector format support paths
- **Area:** spatial-interop
- **Files likely involved:** docs / README, `backend/app/` format adapters
- **Acceptance criteria:** A doc captures which vector formats are supported and
  the conversion path used (e.g. via GDAL/ogr2ogr), so contributors know where
  to add new drivers.
- **Test command:** n/a (docs) — verify against actual supported formats.
- **Design settled:** no — confirm the current format list before writing.

# Quick Task 58: Re-evaluate VRT Creation Placement - Context

**Gathered:** 2026-03-15
**Status:** Ready for planning

<domain>
## Task Boundary

Re-evaluate the placement of the virtual raster creation function for optimal UI/UX. Currently lives as a tab on the /import page alongside Upload File, Register Table, and Service URL. VRT creation is a "compose" action (combining existing rasters), not an "import" action.

</domain>

<decisions>
## Implementation Decisions

### Semantic Placement
- Move VRT creation out of the Import page into the navbar **Create dropdown**
- Must be clearly distinguished from the existing "Dataset" option (which creates empty vector feature tables)
- User noted: "needs to be distinguished from Dataset or apart of this flow"

### Entry Context
- Add a **contextual entry point** on raster dataset detail pages (e.g. "Create VRT from this dataset")
- This button should pre-select the current dataset as a VRT source and navigate to the VRT creator
- Top-level Create dropdown entry also remains

### Form Rendering
- Use a **dedicated full-page route** (e.g. `/vrt/new`)
- Complex search + multi-select + validation benefits from full page space
- Create dropdown item navigates to this page
- Contextual button from detail page navigates here with pre-selected source (e.g. `/vrt/new?source={datasetId}`)

### Claude's Discretion
- Exact label/icon for the Create dropdown item
- How to visually group or separate VRT from Dataset in the dropdown
- Detail page button placement and styling

</decisions>

<specifics>
## Specific Ideas

- Remove the "Virtual Raster" tab from ImportPage entirely
- Add "Virtual Raster" item to Create dropdown menu with distinct icon/description
- Create new route `/vrt/new` that renders the existing VrtCreatorForm
- Support `?source=<datasetId>` query param to pre-select a raster source
- Add "Create VRT" action button on raster dataset detail pages

</specifics>

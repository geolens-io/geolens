# Phase 1102 Summary: ADK Saved Map Composition

**Status:** Complete
**Requirements closed:** ADK-MAP-01, ADK-MAP-02, ADK-MAP-03

## Delivered

- Primary map updated in place: `c39be324-6815-40e5-8143-00a2723827b2`.
- Bonus 3D relief map created/updated: `8dd6a129-8eb0-4ba9-b421-716c83b160dd`.
- Primary map terrain config is durable disabled state: `{"enabled": false, "source_dataset_id": null, "exaggeration": 1.0}`.
- Relief map terrain config is enabled with DEM source `2931c262-0e86-4e23-b14d-55763854e004` and `exaggeration: 1.7`.
- Both maps use the upgraded aerial dataset `4a90aa08-abfc-46f1-bccf-56e479453fb5`, NHD flowlines `4a66b4b6-a9cc-4a87-bb30-3b3ec409f9bd`, NHD waterbodies `c7200cc7-389e-4f39-b225-f7a491891b4f`, and complete 46er peaks `42ac6daa-3b5e-4e06-9cbc-5562191de787`.

## Final Layer Order

1. ADK 46er peaks
2. Hiking trails
3. NHD streams and rivers
4. Blue Line (APA boundary)
5. NHD lakes and ponds
6. Land classification
7. DEM hillshade (1m)
8. TNM/NY Orthos aerial

## Notes

The first compose rerun exposed a script bug: ingest commit returns `202 Import queued`. The script now treats 202 as success and polls the job until complete before composing maps. Phase 1106 smoke later exposed that the canonical saved order still placed rasters above several overlays; the compose script was corrected to assign top-to-bottom sort order with all vectors above DEM/aerial and rerun successfully.

# Quick Task 260325-qrg: Review map sharing/embed controls admin vs map creator alignment - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Task Boundary

Review the admin shared maps page (/admin/shared-maps) and the map creator's SharePanel for alignment, correct wiring, and UI/UX polish. Ensure the admin page accurately reflects backend state and that the map creator's sharing controls are complete and functional.

</domain>

<decisions>
## Implementation Decisions

### Admin edit capabilities
- Admin page stays revoke-only — it's an oversight dashboard, not an editing interface
- Editing share/embed settings happens in the map creator's SharePanel
- Admin can only revoke share tokens and bulk-revoke embed tokens

### Wiring review depth
- End-to-end audit: trace every admin page hook/action to backend endpoints
- Verify status badges, pagination, search, and revoke flows are all correct
- Check that the SharePanel's share/embed controls properly wire to backend APIs

### UI/UX priority
- Fix easy wins: layout issues, missing states, accessibility gaps, polish
- Skip major redesigns

### Claude's Discretion
- SharePanel completeness: check that all controls (embed code, domain restrictions, expiration) are properly wired and functional

</decisions>

<specifics>
## Specific Ideas

- Check if admin page status badges match backend token states (active/expired/revoked/expiring_soon)
- Verify the expandable embed tokens sub-table loads correctly
- Confirm revoke cascades work (revoking share token deactivates embed tokens)
- Check SharePanel handles edge cases: no share token yet, expired token, revoked token

</specifics>

<canonical_refs>
## Canonical References

- Admin page: `frontend/src/pages/admin/AdminSharedMapsPage.tsx`
- Share panel: `frontend/src/components/builder/SharePanel.tsx`
- Admin hooks: `frontend/src/hooks/use-admin.ts`
- Share token API: `frontend/src/api/maps.ts`, `backend/app/maps/router.py`
- Embed token API: `frontend/src/api/embed-tokens.ts`, `backend/app/embed_tokens/router.py`
- Admin endpoints: `backend/app/admin/router.py`, `backend/app/embed_tokens/admin_router.py`

</canonical_refs>

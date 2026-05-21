---
phase: quick-60
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/import/VrtCreateDialog.tsx
  - frontend/src/components/import/VrtCreatorForm.tsx
  - frontend/src/components/layout/Navbar.tsx
  - frontend/src/pages/DatasetPage.tsx
  - frontend/src/App.tsx
  - frontend/src/pages/VrtNewPage.tsx
  - frontend/src/components/import/__tests__/VrtCreatorForm.test.tsx
autonomous: true
requirements: [QUICK-60]

must_haves:
  truths:
    - "Clicking 'Virtual Raster' in the Create dropdown opens a modal dialog, not a new page"
    - "VRT creation form in dialog is fully functional (search, select sources, submit)"
    - "Clicking 'Create VRT' from a raster dataset detail page opens dialog with source pre-selected"
    - "No /vrt/new route exists; navigating to /vrt/new redirects or 404s"
    - "Job progress displays inside the dialog after submission"
  artifacts:
    - path: "frontend/src/components/import/VrtCreateDialog.tsx"
      provides: "Dialog wrapper around VrtCreatorForm"
      exports: ["VrtCreateDialog"]
    - path: "frontend/src/components/layout/Navbar.tsx"
      provides: "CreateMenu and MobileNav using VrtCreateDialog"
    - path: "frontend/src/pages/DatasetPage.tsx"
      provides: "Create VRT button opens dialog instead of navigating"
  key_links:
    - from: "frontend/src/components/layout/Navbar.tsx"
      to: "frontend/src/components/import/VrtCreateDialog.tsx"
      via: "VrtCreateDialog open/onOpenChange state"
      pattern: "VrtCreateDialog.*open"
    - from: "frontend/src/pages/DatasetPage.tsx"
      to: "frontend/src/components/import/VrtCreateDialog.tsx"
      via: "VrtCreateDialog with initialSourceId prop"
      pattern: "VrtCreateDialog.*initialSourceId"
---

<objective>
Convert the VRT creation from a dedicated /vrt/new page to a modal dialog, matching the pattern used by Dataset, Collection, and Map create actions.

Purpose: Consistency — all "Create" dropdown items should open modals, not navigate to separate pages.
Output: VrtCreateDialog component, updated Navbar/DatasetPage, removed VrtNewPage and route.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/create/CreateDatasetDialog.tsx (pattern reference — Dialog with open/onOpenChange)
@frontend/src/components/import/VrtCreatorForm.tsx (existing form to wrap)
@frontend/src/components/layout/Navbar.tsx (CreateMenu + MobileNav)
@frontend/src/pages/DatasetPage.tsx (Create VRT button)
@frontend/src/App.tsx (route to remove)
@frontend/src/components/import/__tests__/VrtCreatorForm.test.tsx (tests to update)

<interfaces>
From frontend/src/components/ui/dialog.tsx:
```typescript
function Dialog({ ...props }: React.ComponentProps<typeof DialogPrimitive.Root>)
function DialogContent({ className, children, showCloseButton = true, ...props })
function DialogHeader({ className, ...props }: React.ComponentProps<"div">)
function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>)
```

From frontend/src/components/import/VrtCreatorForm.tsx:
```typescript
interface VrtCreatorFormProps {
  initialSourceId?: string;
}
export function VrtCreatorForm({ initialSourceId }: VrtCreatorFormProps)
```

Existing dialog pattern (CreateDatasetDialog):
```typescript
interface CreateDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}
export function CreateDatasetDialog({ open, onOpenChange }: CreateDatasetDialogProps)
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create VrtCreateDialog and update VrtCreatorForm for dialog use</name>
  <files>frontend/src/components/import/VrtCreateDialog.tsx, frontend/src/components/import/VrtCreatorForm.tsx</files>
  <action>
    1. Create `VrtCreateDialog.tsx` following the exact pattern from CreateDatasetDialog:
       - Props: `{ open: boolean; onOpenChange: (open: boolean) => void; initialSourceId?: string }`
       - Wraps VrtCreatorForm in Dialog > DialogContent > DialogHeader + DialogTitle
       - Use `sm:max-w-2xl` on DialogContent (the form is wider than other dialogs due to source picker)
       - Pass `initialSourceId` through to VrtCreatorForm
       - Pass an `onSuccess` callback to VrtCreatorForm that closes the dialog after job completes
       - Reset form state when dialog opens (the existing `resetForm` in VrtCreatorForm handles this, but also clear initialSourceId effect)

    2. Modify `VrtCreatorForm` to accept an optional `onClose?: () => void` prop:
       - After successful job completion (when user clicks "Create Another" or similar reset), call `onClose?.()` if provided
       - The JobProgress `onReset` callback should also offer a way to close the dialog. Add a second button "Close" alongside "Create Another" in the JobProgress success state that calls `onClose?.()`
       - Actually, simpler approach: add `onJobStarted?: (jobId: string) => void` prop. When the VRT job is submitted successfully and jobId is set, the dialog can stay open showing JobProgress. No additional close button needed — the dialog's X button already works.

    Simplest approach that matches existing patterns:
    - VrtCreateDialog wraps VrtCreatorForm in a Dialog
    - When dialog closes (via X or overlay click), form resets on next open via useEffect on `open` prop
    - Add `onCreated?: () => void` prop to VrtCreatorForm. Call it after successful mutateAsync (before setJobId). The dialog can use this to optionally close or track state.
    - Actually, keep it even simpler: just wrap VrtCreatorForm in Dialog. Add a useEffect in VrtCreateDialog that resets by remounting VrtCreatorForm with a key that changes when `open` transitions to true. Use `key={openCount}` pattern where openCount increments each time open becomes true.

    Final approach:
    - VrtCreateDialog: Dialog wrapper. Uses a `key` counter that increments when `open` changes from false to true, forcing VrtCreatorForm remount (clean state). This avoids modifying VrtCreatorForm internals.
    - The form content already handles everything including JobProgress display.
    - Use `sm:max-w-2xl` for DialogContent since the form has search picker and source list.
    - Import `useTranslation('import')` for the dialog title using existing `vrt.pageTitle` key.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30</automated>
  </verify>
  <done>VrtCreateDialog component exists, wraps VrtCreatorForm in a Dialog with proper open/onOpenChange interface matching other create dialogs</done>
</task>

<task type="auto">
  <name>Task 2: Wire VrtCreateDialog into Navbar and DatasetPage, remove /vrt/new route</name>
  <files>frontend/src/components/layout/Navbar.tsx, frontend/src/pages/DatasetPage.tsx, frontend/src/App.tsx, frontend/src/pages/VrtNewPage.tsx, frontend/src/components/import/__tests__/VrtCreatorForm.test.tsx</files>
  <action>
    1. **Navbar.tsx — CreateMenu function:**
       - Add `const [vrtOpen, setVrtOpen] = useState(false);` alongside existing dialog states
       - Import `VrtCreateDialog` from `@/components/import/VrtCreateDialog`
       - Replace the `<DropdownMenuItem asChild><Link to="/vrt/new">` with `<DropdownMenuItem onClick={() => setVrtOpen(true)}>` (remove `asChild` and `Link`, keep Layers icon and text)
       - Add `<VrtCreateDialog open={vrtOpen} onOpenChange={setVrtOpen} />` alongside other dialog renders
       - Remove the `DropdownMenuSeparator` before the VRT item — it should be a regular menu item like the others (Dataset, Collection, Map are all direct dialog triggers with no separator)

    2. **Navbar.tsx — MobileNav function:**
       - Add `const [vrtOpen, setVrtOpen] = useState(false);` alongside existing dialog states
       - Import already handled at top level
       - Replace `<NavLink to="/vrt/new" ...>` with `<button className={mobileNavLinkClass({ isActive: false })} onClick={() => { setVrtOpen(true); setOpen(false); }}>` matching the pattern of Dataset/Collection/Map buttons
       - Add `<VrtCreateDialog open={vrtOpen} onOpenChange={setVrtOpen} />` alongside other dialog renders
       - Remove the `<Separator className="my-1" />` before the VRT button

    3. **DatasetPage.tsx:**
       - Import `VrtCreateDialog`
       - Add `const [vrtOpen, setVrtOpen] = useState(false);` state
       - Replace `<Button asChild variant="outline" size="sm"><Link to={...}>` with `<Button variant="outline" size="sm" onClick={() => setVrtOpen(true)}>` (remove `asChild` and `Link`)
       - Add `<VrtCreateDialog open={vrtOpen} onOpenChange={setVrtOpen} initialSourceId={dataset.id} />` near the button
       - Remove `Link` import if no longer used (check other usages first)

    4. **App.tsx:**
       - Remove the `VrtNewPage` lazy import line
       - Remove the `<Route path="vrt/new" element={<VrtNewPage />} />` route

    5. **VrtNewPage.tsx:**
       - Delete the file entirely

    6. **VrtCreatorForm.test.tsx:**
       - Tests render VrtCreatorForm directly, not via the dialog — they should still pass unchanged. Run tests to confirm. If any test references the page wrapper, update accordingly.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx tsc --noEmit --project frontend/tsconfig.json 2>&1 | head -30 && cd frontend && npx vitest run src/components/import/__tests__/VrtCreatorForm.test.tsx --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>VRT creation opens as a dialog from all entry points (navbar Create dropdown desktop + mobile, dataset detail button). /vrt/new route removed. All existing tests pass.</done>
</task>

</tasks>

<verification>
- TypeScript compiles with no errors: `cd frontend && npx tsc --noEmit`
- VrtCreatorForm tests pass: `cd frontend && npx vitest run src/components/import/__tests__/VrtCreatorForm.test.tsx`
- VrtNewPage.tsx no longer exists
- No references to `/vrt/new` route remain in codebase (grep for `vrt/new`)
- VrtCreateDialog follows same interface pattern as CreateDatasetDialog, CollectionCreateDialog, MapCreateDialog
</verification>

<success_criteria>
- All "Create" dropdown items open modal dialogs (no page navigation for create actions)
- VRT creation form works identically in dialog as it did on the standalone page
- Source pre-selection from dataset detail page works via dialog prop
- /vrt/new route is fully removed
- TypeScript and tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/60-make-the-vrt-new-page-a-modal-consistent/60-SUMMARY.md`
</output>

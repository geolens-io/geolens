/**
 * Barrel re-export for LayerStyleEditor.
 *
 * TypeScript module resolution prefers the file `LayerStyleEditor.tsx` over
 * `LayerStyleEditor/index.ts` (file beats directory). Existing callers that
 * import from `'./LayerStyleEditor'` or `'@/components/builder/LayerStyleEditor'`
 * continue to resolve to the orchestrator file without any changes.
 *
 * This barrel exists for discoverability and forward-compatibility — future
 * imports can use the directory form if preferred.
 */
export { LayerStyleEditor, hasUnsavedStyleChanges } from '../LayerStyleEditor';
export type { } from '../LayerStyleEditor';

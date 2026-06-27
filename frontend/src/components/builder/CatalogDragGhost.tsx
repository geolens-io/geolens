// builder-audit STACK-05: extracted from UnifiedStackPanel.tsx into a sibling
// file. Compact pill shown in the DragOverlay during a catalog drag, so the
// overlay reads as a "new-dataset-to-be-added" rather than an existing stack row.

export function CatalogDragGhost({
  recordType,
  name,
}: {
  recordType: string;
  name: string;
}) {
  // Type-icon swatch palette per UI-SPEC section 2.
  // Basemap → primary-50/primary-700; raster/vrt → type-raster-bg/type-raster; default (vector) → type-vector-bg/type-vector.
  let swatchBg: string;
  let swatchColor: string;
  let swatchGlyph: string;
  if (recordType === 'basemap') {
    swatchBg = 'var(--primary-50, oklch(0.97 0.02 250))';
    swatchColor = 'var(--primary-700, oklch(0.40 0.15 250))';
    swatchGlyph = 'B';
  } else if (recordType === 'raster_dataset' || recordType === 'vrt_dataset') {
    swatchBg = 'var(--type-raster-bg, oklch(0.95 0.04 60))';
    swatchColor = 'var(--type-raster, oklch(0.55 0.12 60))';
    swatchGlyph = 'R';
  } else {
    // vector_dataset or unknown
    swatchBg = 'var(--type-vector-bg, oklch(0.95 0.04 145))';
    swatchColor = 'var(--type-vector, oklch(0.45 0.12 145))';
    swatchGlyph = 'V';
  }

  return (
    <div
      data-testid="catalog-ghost"
      className="pointer-events-none flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 cursor-grabbing"
      style={{
        boxShadow: '0 4px 12px oklch(0 0 0 / 15%)',
        maxWidth: 260,
        minHeight: 36,
      }}
    >
      {/* Type swatch */}
      <span
        aria-hidden="true"
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded"
        style={{ background: swatchBg, color: swatchColor }}
      >
        <span className="text-[10px] font-semibold uppercase">{swatchGlyph}</span>
      </span>
      {/* Dataset name */}
      <span className="truncate text-sm" style={{ maxWidth: 200 }}>{name}</span>
    </div>
  );
}

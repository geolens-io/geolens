// feat(#1241): which save a preview earns. The two guards this encodes —
// truncation and the upload capability — are the reason the snapshot path
// exists at all, so they are pinned here rather than only through the UI.
import { previewSaveMode } from '../ephemeral-preview';

describe('previewSaveMode', () => {
  it('offers nothing without a preview', () => {
    expect(previewSaveMode(null, true)).toBe('none');
    expect(previewSaveMode(undefined, true)).toBe('none');
  });

  it('snapshots a complete chat preview', () => {
    expect(previewSaveMode({ featureCount: 240 }, true)).toBe('snapshot');
  });

  it('refuses to snapshot a server-truncated preview (#674/#1076)', () => {
    expect(previewSaveMode({ featureCount: 500, truncated: true }, true)).toBe('truncated');
  });

  // The analysis handoff re-runs the operation server-side and materializes the
  // complete result — the capped PREVIEW says nothing about what it would save,
  // so #675's path must survive the guard added for the snapshot path.
  it('keeps the #675 analysis handoff on a truncated preview', () => {
    expect(
      previewSaveMode(
        { featureCount: 500, truncated: true, analysis: { operation: 'buffer', layerId: 'l1' } },
        true,
      ),
    ).toBe('analysis');
  });

  it('keeps the analysis handoff for a caller who cannot upload', () => {
    // Materializing an analysis is a different endpoint with its own gate;
    // #1241 must not narrow a path it did not add.
    expect(
      previewSaveMode({ featureCount: 12, analysis: { operation: 'centroid' } }, false),
    ).toBe('analysis');
  });

  it('offers no snapshot without the upload capability', () => {
    expect(previewSaveMode({ featureCount: 240 }, false)).toBe('none');
    // Not even the disabled/explained state — the affordance is not theirs.
    expect(previewSaveMode({ featureCount: 500, truncated: true }, false)).toBe('none');
  });

  it('offers no snapshot of an empty result', () => {
    expect(previewSaveMode({ featureCount: 0 }, true)).toBe('none');
  });
});

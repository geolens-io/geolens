import type { BaseStyleEditorProps } from './types';

/**
 * RasterEditor — placeholder for raster layer style controls.
 * Raster layers currently have no per-property controls in the builder
 * (opacity is handled at the orchestrator level via the master opacity slider).
 * TODO(1047-05): further split — add brightness/contrast/saturation controls here.
 */
export function RasterEditor({ t }: BaseStyleEditorProps) {
  return (
    <div className="text-xs text-muted-foreground">
      {t('style.rasterControls', { defaultValue: 'Use the opacity slider above to adjust raster transparency.' })}
    </div>
  );
}

export default RasterEditor;

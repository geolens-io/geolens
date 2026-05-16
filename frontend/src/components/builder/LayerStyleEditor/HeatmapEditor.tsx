import { HeatmapStyleControls } from '../HeatmapStyleControls';
import type { BaseStyleEditorProps } from './types';

/**
 * HeatmapEditor — thin wrapper that passes BaseStyleEditorProps
 * to the already-separate HeatmapStyleControls component.
 */
export function HeatmapEditor({
  layer,
  paint,
  onHeatmapPaintChange,
}: BaseStyleEditorProps) {
  // HeatmapStyleControls expects the merged controlPaint
  return (
    <HeatmapStyleControls
      layer={{ ...layer, paint }}
      onPaintChange={onHeatmapPaintChange}
    />
  );
}

export default HeatmapEditor;

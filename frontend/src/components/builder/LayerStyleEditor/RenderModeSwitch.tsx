import type React from 'react';
import { FillEditor } from './FillEditor';
import { LineEditor } from './LineEditor';
import { CircleEditor } from './CircleEditor';
import { SymbolEditor } from './SymbolEditor';
import { HeatmapEditor } from './HeatmapEditor';
import { ClusterEditor } from './ClusterEditor';
import { RasterEditor } from './RasterEditor';
import type { BaseStyleEditorProps } from './types';

/**
 * Dispatch key type for the RenderModeSwitch lookup table.
 * Derived from geomType + PointRenderMode (for circle layers).
 *
 * CD-19 fix: replaces 200+ LOC of nested ternaries with a flat lookup table.
 */
export type EditorDispatchKey =
  | 'fill'
  | 'line'
  | 'circle'
  | 'heatmap'
  | 'symbol'
  | 'cluster'
  | 'raster';

interface RenderModeSwitchProps extends BaseStyleEditorProps {
  /** The resolved dispatch key. Computed by the orchestrator from geomType + renderMode. */
  dispatchKey: EditorDispatchKey | string;
}

/**
 * Lookup-table component dispatcher (CD-19 fix).
 *
 * Uses a record of EditorDispatchKey → Component instead of nested ternaries.
 * If the dispatchKey is unrecognized, logs a DEV-only warning and returns null.
 */
const editorComponents: Record<EditorDispatchKey, React.ComponentType<BaseStyleEditorProps>> = {
  fill: FillEditor,
  line: LineEditor,
  circle: CircleEditor,
  heatmap: HeatmapEditor,
  symbol: SymbolEditor,
  cluster: ClusterEditor,
  raster: RasterEditor,
};

export function RenderModeSwitch({ dispatchKey, ...rest }: RenderModeSwitchProps): React.JSX.Element | null {
  const Editor = editorComponents[dispatchKey as EditorDispatchKey];

  if (!Editor) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`[RenderModeSwitch] Unrecognized dispatchKey: "${dispatchKey}". Returning null.`);
    }
    return null;
  }

  return <Editor {...rest} />;
}

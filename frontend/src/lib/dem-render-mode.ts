import type { StyleConfig } from '@/types/api';

type LayerStyle = {
  render_mode?: StyleConfig['render_mode'];
  [key: string]: unknown;
};

export function effectiveDemRenderMode(
  styleConfig: LayerStyle | null | undefined,
  isDem?: boolean | null,
): StyleConfig['render_mode'] | undefined {
  const renderMode = styleConfig?.render_mode;
  if (isDem !== true) return renderMode;
  return renderMode === 'terrain' ? 'terrain' : 'hillshade';
}

export function normalizeDemStyleConfig<TStyle extends LayerStyle>(
  styleConfig: TStyle | null | undefined,
  isDem?: boolean | null,
): TStyle | null {
  if (isDem !== true) return styleConfig ?? null;

  return {
    ...(styleConfig ?? {}),
    render_mode: effectiveDemRenderMode(styleConfig, true),
  } as TStyle;
}

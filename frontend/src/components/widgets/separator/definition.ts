import { defineWidget } from '../contract';
import { SeparatorBlockFallback } from './SeparatorBlockFallback';

export type SeparatorStyle = 'line' | 'gap';

export interface SeparatorConfig {
  style: SeparatorStyle;
}

export const SEPARATOR_DEFAULT_CONFIG: SeparatorConfig = { style: 'line' };

function parseSeparatorConfig(config: unknown): SeparatorConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  const keys = Object.keys(config);
  if (keys.some((key) => key !== 'style')) return null;
  const { style } = config as { style?: unknown };
  if (style === undefined) return { style: 'line' };
  return style === 'line' || style === 'gap' ? { style } : null;
}

export const separatorWidget = defineWidget<SeparatorConfig>({
  type: 'separator',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.separator.label',
  i18nKeys: [],
  defaultConfig: SEPARATOR_DEFAULT_CONFIG,
  parseConfig: parseSeparatorConfig,
  loadRenderer: async () => ({ default: SeparatorBlockFallback }),
  Fallback: SeparatorBlockFallback,
});

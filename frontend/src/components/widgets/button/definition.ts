import { isSafeHttpUrl } from '@/lib/safe-http-url';
import { defineWidget } from '../contract';
import { ButtonBlockFallback } from './ButtonBlockFallback';

export interface ButtonConfig {
  label: string;
  url: string;
  new_tab?: boolean;
}

/** The server's caps on a button block (`ButtonConfig` in widgets/schemas.py). */
export const BUTTON_LABEL_MAX_LENGTH = 120;
export const BUTTON_URL_MAX_LENGTH = 2048;

/** What a new button starts with; the author fills in both fields. */
export const BUTTON_DEFAULT_CONFIG: Required<ButtonConfig> = { label: '', url: '', new_tab: false };

const KEYS = new Set(['label', 'url', 'new_tab']);

/** Whether the server would refuse this button for its label or address. */
export function buttonNeedsAttention(config: ButtonConfig): boolean {
  return config.label.trim() === '' || !isSafeHttpUrl(config.url);
}

// The address is checked where the button renders, not here: a stored button
// with an unsafe address still reads, and shows its label as plain text.
function parseButtonConfig(config: unknown): ButtonConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  if (!Object.keys(config).every((key) => KEYS.has(key))) return null;
  const { label, url, new_tab } = config as { label?: unknown; url?: unknown; new_tab?: unknown };
  if (typeof label !== 'string' || label.trim() === '' || [...label].length > BUTTON_LABEL_MAX_LENGTH) return null;
  if (typeof url !== 'string' || url.length > BUTTON_URL_MAX_LENGTH) return null;
  if (new_tab !== undefined && typeof new_tab !== 'boolean') return null;
  return { label, url, ...(new_tab ? { new_tab: true } : {}) };
}

export const buttonWidget = defineWidget<ButtonConfig>({
  type: 'button',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.button.label',
  i18nKeys: ['types.button.opensInNewTab'],
  defaultConfig: BUTTON_DEFAULT_CONFIG,
  parseConfig: parseButtonConfig,
  // The fallback is the whole widget, so there is no heavier renderer to split out.
  loadRenderer: async () => ({ default: ButtonBlockFallback }),
  Fallback: ButtonBlockFallback,
});

import { defineWidget } from '../contract';
import { ImageBlockFallback } from './ImageBlockFallback';

export interface ImageConfig {
  alt: string;
  caption?: string | null;
}

/** The server's caps on an image block's text (`ImageConfig` in widgets/schemas.py). */
export const IMAGE_ALT_MAX_LENGTH = 500;
export const IMAGE_CAPTION_MAX_LENGTH = 500;

/** What a new image block starts with; the author writes the alt text after uploading. */
export const IMAGE_DEFAULT_CONFIG: ImageConfig = { alt: '', caption: null };

const KEYS = new Set(['alt', 'caption']);

const withinMax = (text: string, max: number) => [...text].length <= max;

/** Whether `alt` is text the server takes: not blank, and within its cap. */
export function validImageAlt(alt: string): boolean {
  return alt.trim() !== '' && withinMax(alt.trim(), IMAGE_ALT_MAX_LENGTH);
}

function parseImageConfig(config: unknown): ImageConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  if (!Object.keys(config).every((key) => KEYS.has(key))) return null;
  const { alt, caption } = config as { alt?: unknown; caption?: unknown };
  if (typeof alt !== 'string' || !validImageAlt(alt)) return null;
  if (caption === undefined || caption === null) return { alt };
  if (typeof caption !== 'string' || !withinMax(caption, IMAGE_CAPTION_MAX_LENGTH)) return null;
  return { alt, caption };
}

export const imageWidget = defineWidget<ImageConfig>({
  type: 'image',
  v: 1,
  surfaces: ['story'],
  asset: true,
  labelKey: 'types.image.label',
  i18nKeys: ['types.image.description', 'types.image.loading'],
  defaultConfig: IMAGE_DEFAULT_CONFIG,
  parseConfig: parseImageConfig,
  loadRenderer: () => import('./ImageBlockRenderer'),
  Fallback: ImageBlockFallback,
});

import { defineWidget } from '../contract';
import { ImageBlockFallback } from './ImageBlockFallback';

export interface ImageConfig {
  /** Required unless the image is decorative. */
  alt?: string | null;
  /** Readers get an empty alt: the image adds nothing they need. */
  decorative?: boolean | null;
  caption?: string | null;
}

/** The server's caps on an image block's text (`ImageConfig` in widgets/schemas.py). */
export const IMAGE_ALT_MAX_LENGTH = 500;
export const IMAGE_CAPTION_MAX_LENGTH = 500;

/** What a new image block starts with; the author writes the alt text after uploading. */
export const IMAGE_DEFAULT_CONFIG: ImageConfig = { alt: '', caption: null };

const KEYS = new Set(['alt', 'decorative', 'caption']);

const withinMax = (text: string, max: number) => [...text].length <= max;

/** Whether `alt` is text the server takes: not blank, and within its cap. */
function validImageAlt(alt: string | null | undefined): boolean {
  const text = alt?.trim() ?? '';
  return text !== '' && withinMax(text, IMAGE_ALT_MAX_LENGTH);
}

/** Whether the server would refuse this image for its alt text. */
export function imageNeedsAlt(config: ImageConfig): boolean {
  return !config.decorative && !validImageAlt(config.alt);
}

/** The alt attribute readers get: empty for a decorative image. */
export function readerAlt(config: ImageConfig): string {
  return config.decorative ? '' : (config.alt ?? '');
}

function parseImageConfig(config: unknown): ImageConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  if (!Object.keys(config).every((key) => KEYS.has(key))) return null;
  const { alt, decorative, caption } = config as { alt?: unknown; decorative?: unknown; caption?: unknown };
  if (decorative !== undefined && typeof decorative !== 'boolean') return null;
  if (alt !== undefined && alt !== null && (typeof alt !== 'string' || !validImageAlt(alt))) return null;
  const parsed: ImageConfig = {};
  if (typeof alt === 'string') parsed.alt = alt;
  if (decorative) parsed.decorative = true;
  if (imageNeedsAlt(parsed)) return null;
  if (caption === undefined || caption === null) return parsed;
  if (typeof caption !== 'string' || !withinMax(caption, IMAGE_CAPTION_MAX_LENGTH)) return null;
  return { ...parsed, caption };
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

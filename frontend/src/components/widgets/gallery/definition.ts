import { defineWidget } from '../contract';
import { parseImageFields, type ImageConfig } from '../image/definition';
import { GalleryBlockFallback } from './GalleryBlockFallback';

export interface GalleryImageConfig extends ImageConfig {
  asset_id: string;
}

export interface GalleryConfig {
  images: GalleryImageConfig[];
}

/** The server's cap on the images in one gallery or carousel (`MAX_GALLERY_IMAGES` in widgets/schemas.py). */
export const MAX_GALLERY_IMAGES = 12;

/** A key for each entry that follows its image, also where an image appears twice. */
export function entryKeys(images: readonly GalleryImageConfig[]): string[] {
  const seen = new Map<string, number>();
  return images.map(({ asset_id }) => {
    const n = seen.get(asset_id) ?? 0;
    seen.set(asset_id, n + 1);
    return `${asset_id}:${n}`;
  });
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseGalleryConfig(config: unknown): GalleryConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  if (!Object.keys(config).every((key) => key === 'images')) return null;
  const { images } = config as { images?: unknown };
  if (!Array.isArray(images) || images.length < 1 || images.length > MAX_GALLERY_IMAGES) return null;
  const parsed: GalleryImageConfig[] = [];
  for (const image of images) {
    const assetId = (image as { asset_id?: unknown } | null)?.asset_id;
    if (typeof assetId !== 'string' || !UUID.test(assetId)) return null;
    const text = parseImageFields(image, ['asset_id']);
    if (text === null) return null;
    parsed.push({ ...text, asset_id: assetId });
  }
  return { images: parsed };
}

export const galleryWidget = defineWidget<GalleryConfig>({
  type: 'gallery',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.gallery.label',
  i18nKeys: ['types.image.description', 'types.image.loading'],
  defaultConfig: { images: [] },
  parseConfig: parseGalleryConfig,
  loadRenderer: () => import('./GalleryBlockRenderer'),
  Fallback: GalleryBlockFallback,
});

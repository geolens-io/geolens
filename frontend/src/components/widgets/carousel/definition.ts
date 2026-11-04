import { defineWidget } from '../contract';
import { GalleryBlockFallback } from '../gallery/GalleryBlockFallback';
import { parseGalleryConfig, type GalleryConfig } from '../gallery/definition';

export const carouselWidget = defineWidget<GalleryConfig>({
  type: 'carousel',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.carousel.label',
  i18nKeys: [
    'types.image.description',
    'types.image.loading',
    'types.carousel.previous',
    'types.carousel.next',
    'types.carousel.position',
  ],
  defaultConfig: { images: [] },
  parseConfig: parseGalleryConfig,
  loadRenderer: () => import('./CarouselBlockRenderer'),
  Fallback: GalleryBlockFallback,
});

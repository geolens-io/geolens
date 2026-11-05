import { defineWidget } from '../contract';
import { FrameBlockFallback } from './FrameBlockFallback';
import { FRAME_DEFAULT_CONFIG, parseFrameConfig, type FrameConfig } from './frame';

/** A page from a host an admin approved, shown in a sandboxed frame. */
export const embedWidget = defineWidget<FrameConfig>({
  type: 'embed',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.embed.label',
  i18nKeys: ['types.embed.unavailable', 'types.button.opensInNewTab', 'types.embed.originalLink'],
  defaultConfig: FRAME_DEFAULT_CONFIG,
  parseConfig: parseFrameConfig,
  loadRenderer: () => import('./EmbedBlockRenderer'),
  Fallback: FrameBlockFallback,
});

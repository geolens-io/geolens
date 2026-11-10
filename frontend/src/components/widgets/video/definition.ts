import { defineWidget } from '../contract';
import { FrameBlockFallback } from '../embed/FrameBlockFallback';
import { FRAME_DEFAULT_CONFIG, parseFrameConfig, type FrameConfig } from '../embed/frame';

/** A video player from a host an admin approved, shown in a sandboxed 16:9 frame. */
export const videoWidget = defineWidget<FrameConfig>({
  type: 'video',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.video.label',
  i18nKeys: ['types.video.unavailable', 'types.button.opensInNewTab', 'types.embed.originalLink'],
  defaultConfig: FRAME_DEFAULT_CONFIG,
  parseConfig: parseFrameConfig,
  loadRenderer: () => import('./VideoBlockRenderer'),
  Fallback: FrameBlockFallback,
});

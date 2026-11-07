import type { WidgetRenderProps } from '../contract';
import type { FrameConfig } from './frame';
import { FrameBlockRenderer } from './FrameBlockRenderer';

export default function EmbedBlockRenderer(props: WidgetRenderProps<FrameConfig>) {
  return <FrameBlockRenderer {...props} kind="embed" />;
}

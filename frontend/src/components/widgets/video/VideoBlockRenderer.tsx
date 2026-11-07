import type { WidgetRenderProps } from '../contract';
import type { FrameConfig } from '../embed/frame';
import { FrameBlockRenderer } from '../embed/FrameBlockRenderer';

export default function VideoBlockRenderer(props: WidgetRenderProps<FrameConfig>) {
  return <FrameBlockRenderer {...props} kind="video" />;
}

import type { WidgetRenderProps } from '../contract';
import type { MarkdownTextConfig } from './definition';

/** The Markdown source as plain text: readable without the renderer chunk. */
export function MarkdownTextFallback({ config }: WidgetRenderProps<MarkdownTextConfig>) {
  return <div className="whitespace-pre-wrap break-words text-sm">{config.markdown}</div>;
}

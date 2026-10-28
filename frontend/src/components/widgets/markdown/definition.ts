import { defineWidget } from '../contract';
import { MarkdownTextFallback } from './MarkdownTextFallback';

export interface MarkdownTextConfig {
  text: string;
}

export const MARKDOWN_TEXT_MAX_LENGTH = 20_000;

function parseMarkdownTextConfig(config: unknown): MarkdownTextConfig | null {
  if (typeof config !== 'object' || config === null || Array.isArray(config)) return null;
  const keys = Object.keys(config);
  if (keys.length !== 1 || keys[0] !== 'text') return null;
  const { text } = config as { text: unknown };
  if (typeof text !== 'string' || [...text].length > MARKDOWN_TEXT_MAX_LENGTH) return null;
  return { text };
}

export const markdownTextWidget = defineWidget<MarkdownTextConfig>({
  type: 'markdown',
  v: 1,
  surfaces: ['story'],
  labelKey: 'types.markdown.label',
  i18nKeys: ['types.markdown.imageNotShown', 'types.markdown.imageNotShownAlt'],
  defaultConfig: { text: '' },
  parseConfig: parseMarkdownTextConfig,
  loadRenderer: () => import('./MarkdownTextRenderer'),
  Fallback: MarkdownTextFallback,
});

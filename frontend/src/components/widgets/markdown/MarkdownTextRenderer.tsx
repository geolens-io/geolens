import Markdown, { type Components } from 'react-markdown';
import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import type { MarkdownTextConfig } from './definition';

// Without rehype-raw, react-markdown shows raw HTML as literal text and never
// renders it. Its default URL transform already drops javascript: and data: links.
const components: Components = {
  a: ({ node: _node, children, ...props }) => (
    <a {...props} rel="noopener noreferrer nofollow">
      {children}
    </a>
  ),
  img: function BlockedImage({ alt }) {
    // The CSP allows any https image, so the renderer is what keeps a story
    // from loading third-party images. Uploaded images go in image blocks,
    // which fetch with the reader's token.
    const { t } = useTranslation('widgets');
    return (
      <span className="text-muted-foreground italic">
        {alt
          ? t('types.markdown.imageNotShownAlt', { alt })
          : t('types.markdown.imageNotShown')}
      </span>
    );
  },
};

export default function MarkdownTextRenderer({ config }: WidgetRenderProps<MarkdownTextConfig>) {
  return (
    <div className="space-y-3 break-words text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:font-mono [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:font-semibold [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown components={components}>{config.markdown}</Markdown>
    </div>
  );
}

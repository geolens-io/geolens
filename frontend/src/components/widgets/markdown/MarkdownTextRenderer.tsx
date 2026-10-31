import { useMemo, type ComponentProps } from 'react';
import Markdown, { defaultUrlTransform, type Components, type ExtraProps } from 'react-markdown';
import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import type { MarkdownTextConfig } from './definition';

// Without rehype-raw, react-markdown shows raw HTML as literal text and never
// renders it. Its default URL transform drops javascript: and data: links,
// and keeps irc, ircs and xmpp ones, which `urlTransform` removes.
const LINK_PROTOCOL = /^(https?|mailto):/i;
const RELATIVE_OR_ANCHOR = /^[^:]*$|^[^:]*[/?#]/;

function urlTransform(url: string): string {
  const safe = defaultUrlTransform(url);
  return LINK_PROTOCOL.test(safe) || RELATIVE_OR_ANCHOR.test(safe) ? safe : '';
}

function heading(level: number) {
  const Tag = `h${Math.min(level, 6)}` as 'h3';
  return function ShiftedHeading({ node: _node, children, ...props }: ComponentProps<'h1'> & ExtraProps) {
    return <Tag {...props}>{children}</Tag>;
  };
}

function componentsFor(firstHeading: number): Components {
  return {
    ...Object.fromEntries([0, 1, 2, 3, 4, 5].map((rank) => [`h${rank + 1}`, heading(firstHeading + rank)])),
    // A link whose target the transform dropped reads as its text.
    a: ({ node: _node, children, ...props }) =>
      props.href ? (
        <a {...props} rel="noopener noreferrer nofollow">
          {children}
        </a>
      ) : (
        <>{children}</>
      ),
    img: function BlockedImage({ alt }) {
      // The CSP allows any https image, so the renderer is what keeps a story
      // or dashboard from loading third-party images. Uploaded images go in
      // image blocks, which fetch with the reader's token.
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
}

/** Headings start at `headingLevel`, h3 by default: under a story chapter's h2, or a dashboard panel's. */
export default function MarkdownTextRenderer({ config, headingLevel = 3 }: WidgetRenderProps<MarkdownTextConfig>) {
  const components = useMemo(() => componentsFor(headingLevel), [headingLevel]);
  return (
    <div className="space-y-3 break-words text-sm leading-relaxed [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:font-mono [&_h3]:text-lg [&_h3]:font-semibold [&_h4]:font-semibold [&_h5]:font-semibold [&_h6]:font-semibold [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown components={components} urlTransform={urlTransform}>
        {config.text}
      </Markdown>
    </div>
  );
}

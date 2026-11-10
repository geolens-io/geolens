/**
 * Popup rich-text helpers — detect URLs in popup property values and classify
 * them as image / video / plain link.
 *
 * Defense-in-depth XSS gate: the URL regex only matches `http://` and
 * `https://` schemes. javascript: / data: / vbscript: URLs are NEVER returned
 * as URL segments. React JSX text-node rendering is the secondary gate —
 * never pass substituted output through `dangerouslySetInnerHTML`.
 *
 * This module is pure (no React, no DOM) and deterministic.
 */

type UrlKind = 'image' | 'video' | 'other';

interface UrlClassification {
  kind: UrlKind;
  /** Original URL to use as the media src or link destination. */
  srcUrl: string;
}

type RichSegment = { kind: 'text'; value: string } | { kind: 'url'; value: string };

// XSS gate: only http:// and https:// match; javascript:/data:/vbscript: never do.
const URL_RE = /https?:\/\/[^\s<>"']+/gi;

/**
 * Strip trailing sentence-ending punctuation from a matched URL token.
 * CommonMark / GitHub / Slack all apply this post-match trim: `.`, `,`, `;`,
 * `:`, `!`, `?`, `"`, `'`, `)`, `]` are almost never valid URL endings but are
 * frequently appended by prose authors ("See https://example.com, for details").
 *
 * Parentheses: a closing `)` is stripped only when there is no matching `(`
 * in the URL body, preserving Wikipedia-style `/wiki/Foo_(bar)` links.
 */
export function trimTrailingPunctuation(url: string): string {
  return url.replace(/[.,;:!?"')\]]+$/, (suffix) => {
    // Retain ) if the URL body already contains a matching (
    const body = url.slice(0, url.length - suffix.length);
    const hasOpenParen = body.includes('(');
    return hasOpenParen ? suffix : '';
  });
}

const IMAGE_EXTS = /\.(jpe?g|png|gif|webp|svg)(\?[^#]*)?(#.*)?$/i;
const VIDEO_EXTS = /\.(mp4|webm|mov)(\?[^#]*)?(#.*)?$/i;

/**
 * Split `text` into an ordered array of text and URL segments. URLs are
 * identified by the XSS-gated `URL_RE` regex (http/https only). Segments
 * whose `kind` is `'url'` are safe to render as `<a href>` anchors; segments
 * whose `kind` is `'text'` are safe React text nodes.
 *
 * Trailing sentence-ending punctuation is stripped from each URL segment via
 * `trimTrailingPunctuation`. Stripped punctuation is re-appended to the
 * following text segment so the overall displayed text is unchanged.
 */
export function splitTextWithUrls(text: string): RichSegment[] {
  const segments: RichSegment[] = [];
  let lastIndex = 0;
  let foundUrl = false;
  // Exec loop for each match index; a fresh regex avoids sharing lastIndex with URL_RE.
  const re = new RegExp(URL_RE.source, URL_RE.flags);
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    foundUrl = true;
    const rawUrl = match[0];
    const trimmedUrl = trimTrailingPunctuation(rawUrl);
    const stripped = rawUrl.slice(trimmedUrl.length); // punctuation shaved off
    const start = match.index;
    const end = start + rawUrl.length;
    // Text before this URL (skip empty leading text segments).
    const pre = text.slice(lastIndex, start);
    if (pre.length > 0) segments.push({ kind: 'text', value: pre });
    segments.push({ kind: 'url', value: trimmedUrl });
    // Re-inject stripped trailing punctuation as a text segment so the
    // displayed output is visually identical to the original string.
    if (stripped.length > 0) segments.push({ kind: 'text', value: stripped });
    lastIndex = end;
  }

  if (!foundUrl) {
    // No URLs — return a single text segment for the whole string.
    return [{ kind: 'text', value: text }];
  }

  // Remaining text after the last URL (skip if empty).
  const trailing = text.slice(lastIndex);
  if (trailing.length > 0) segments.push({ kind: 'text', value: trailing });

  return segments;
}

/**
 * Classify a URL as image, video, or plain link, retaining the
 * original URL for rendering.
 */
export function classifyUrl(url: string): UrlClassification {
  if (IMAGE_EXTS.test(url)) {
    return { kind: 'image', srcUrl: url };
  }
  if (VIDEO_EXTS.test(url)) {
    return { kind: 'video', srcUrl: url };
  }
  return { kind: 'other', srcUrl: url };
}

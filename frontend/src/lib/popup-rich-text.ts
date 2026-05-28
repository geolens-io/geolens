/**
 * Popup rich-text helpers — detect URLs in popup property values and classify
 * them as image / video / YouTube / plain link.
 *
 * Defense-in-depth XSS gate: the URL regex only matches `http://` and
 * `https://` schemes. javascript: / data: / vbscript: URLs are NEVER returned
 * as URL segments. React JSX text-node rendering is the secondary gate —
 * never pass substituted output through `dangerouslySetInnerHTML`.
 *
 * This module is pure (no React, no DOM). All exports are deterministic
 * functions that can be tested in isolation.
 */

export type UrlKind = 'image' | 'video' | 'youtube' | 'other';

export interface UrlClassification {
  kind: UrlKind;
  /** Canonical URL to use as the media src (embed URL for YouTube; original for others). */
  srcUrl: string;
}

export type RichSegment = { kind: 'text'; value: string } | { kind: 'url'; value: string };

// XSS gate: ONLY match http:// and https:// — javascript:/data:/vbscript: never match.
const URL_RE = /https?:\/\/[^\s<>"']+/gi;

const IMAGE_EXTS = /\.(jpe?g|png|gif|webp|svg)(\?[^#]*)?(#.*)?$/i;
const VIDEO_EXTS = /\.(mp4|webm|mov)(\?[^#]*)?(#.*)?$/i;
const YT_HOSTS = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)/i;
// ID must be exactly 11 chars from [A-Za-z0-9_-]
const YT_ID_RE = /(?:v=|youtu\.be\/|embed\/|shorts\/)([A-Za-z0-9_-]{11})(?:[&?#]|$)/;

/**
 * Return the regex matches for http/https URLs found in `text`, or null if
 * none are found. XSS gate: javascript:/data:/vbscript: schemes are excluded
 * because the regex only matches `https?://`.
 */
export function detectUrls(text: string): RegExpMatchArray | null {
  return text.match(URL_RE);
}

/**
 * Split `text` into an ordered array of text and URL segments. URLs are
 * identified by the XSS-gated `URL_RE` regex (http/https only). Segments
 * whose `kind` is `'url'` are safe to render as `<a href>` anchors; segments
 * whose `kind` is `'text'` are safe React text nodes.
 */
export function splitTextWithUrls(text: string): RichSegment[] {
  const segments: RichSegment[] = [];
  let lastIndex = 0;
  let foundUrl = false;
  // Use exec loop to get the index of each match. Build a fresh regex from the
  // same source so we don't share lastIndex state with module-level URL_RE.
  const re = new RegExp(URL_RE.source, URL_RE.flags);
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    foundUrl = true;
    const start = match.index;
    const end = start + match[0].length;
    // Text before this URL (skip empty leading text segments).
    const pre = text.slice(lastIndex, start);
    if (pre.length > 0) segments.push({ kind: 'text', value: pre });
    segments.push({ kind: 'url', value: match[0] });
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
 * Extract the canonical YouTube embed URL (`https://www.youtube.com/embed/<ID>`)
 * from watch?v=, youtu.be/, shorts/, or embed/ forms. Returns null when the
 * URL is not a recognised YouTube URL or lacks a valid 11-character video ID.
 */
export function normalizeYouTubeEmbed(url: string): string | null {
  if (!YT_HOSTS.test(url)) return null;
  const match = YT_ID_RE.exec(url);
  if (!match) return null;
  const id = match[1];
  // Belt-and-suspenders: verify exactly 11 chars (the regex group handles it
  // but the fence makes the contract explicit for future maintainers).
  if (id.length !== 11) return null;
  return `https://www.youtube.com/embed/${id}`;
}

/**
 * Classify a URL as image, video, YouTube embed, or plain link. The returned
 * `srcUrl` is the canonical URL to use for rendering: the embed URL for
 * YouTube, the original URL for all other kinds.
 */
export function classifyUrl(url: string): UrlClassification {
  // YouTube: check before extension-based checks (YouTube URLs don't have media extensions).
  const embedUrl = normalizeYouTubeEmbed(url);
  if (embedUrl !== null) {
    return { kind: 'youtube', srcUrl: embedUrl };
  }
  if (IMAGE_EXTS.test(url)) {
    return { kind: 'image', srcUrl: url };
  }
  if (VIDEO_EXTS.test(url)) {
    return { kind: 'video', srcUrl: url };
  }
  return { kind: 'other', srcUrl: url };
}

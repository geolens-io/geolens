import { describe, it, expect } from 'vitest';
import {
  splitTextWithUrls,
  classifyUrl,
  trimTrailingPunctuation,
} from '../popup-rich-text';

// ---------------------------------------------------------------------------
// splitTextWithUrls
// ---------------------------------------------------------------------------

describe('splitTextWithUrls', () => {
  it('EASY-11 — splits text with embedded URL into [text, url, text] segments', () => {
    const result = splitTextWithUrls('See https://example.com for details');
    expect(result).toHaveLength(3);
    expect(result[0]).toEqual({ kind: 'text', value: 'See ' });
    expect(result[1]).toEqual({ kind: 'url', value: 'https://example.com' });
    expect(result[2]).toEqual({ kind: 'text', value: ' for details' });
  });

  it('EASY-11 — returns single text segment when no URLs present', () => {
    const result = splitTextWithUrls('Just plain text');
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ kind: 'text', value: 'Just plain text' });
  });

  it('EASY-11 — returns single url segment when entire value is a URL', () => {
    const result = splitTextWithUrls('https://example.com');
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ kind: 'url', value: 'https://example.com' });
  });

  it('WR-01 — strips trailing comma: "See https://example.com, for more" → URL has no comma', () => {
    const result = splitTextWithUrls('See https://example.com, for more');
    // URL segment should be clean; comma re-appended as text
    const urlSeg = result.find((s) => s.kind === 'url');
    expect(urlSeg?.value).toBe('https://example.com');
    // The comma must still appear somewhere in the output so displayed text is unchanged
    const textContent = result
      .filter((s) => s.kind === 'text')
      .map((s) => s.value)
      .join('');
    expect(textContent).toContain(',');
  });

  it('WR-01 — strips trailing period from standalone URL', () => {
    const result = splitTextWithUrls('visit https://example.com.');
    expect(result[0]).toEqual({ kind: 'text', value: 'visit ' });
    const urlSeg = result.find((s) => s.kind === 'url');
    expect(urlSeg?.value).toBe('https://example.com');
  });

  it('EASY-11 — matches multiple URLs in one text value → 4 segments (empty trailing text omitted)', () => {
    const result = splitTextWithUrls('A https://a.com and B https://b.com');
    // 4 segments: text + url + text + url (no trailing text because string ends at last URL)
    expect(result).toHaveLength(4);
    expect(result[0]).toEqual({ kind: 'text', value: 'A ' });
    expect(result[1]).toEqual({ kind: 'url', value: 'https://a.com' });
    expect(result[2]).toEqual({ kind: 'text', value: ' and B ' });
    expect(result[3]).toEqual({ kind: 'url', value: 'https://b.com' });
  });

  it('EASY-11 — rejects javascript: URL: returned as single text segment (XSS gate)', () => {
    const result = splitTextWithUrls('click here javascript:alert(1)');
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe('text');
    // no url segments
    expect(result.every((s) => s.kind !== 'url')).toBe(true);
  });

  it('EASY-11 — rejects data: URL: returned as single text segment (XSS gate)', () => {
    const result = splitTextWithUrls('data:image/png;base64,XXX');
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe('text');
    expect(result.every((s) => s.kind !== 'url')).toBe(true);
  });

  it('EASY-11 — rejects vbscript: URL: returned as single text segment (XSS gate)', () => {
    const result = splitTextWithUrls('vbscript:MsgBox("XSS")');
    expect(result).toHaveLength(1);
    expect(result[0].kind).toBe('text');
    expect(result.every((s) => s.kind !== 'url')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// classifyUrl
// ---------------------------------------------------------------------------

describe('classifyUrl', () => {
  it('EASY-11 — classifies https://x.com/foo.jpg as image', () => {
    expect(classifyUrl('https://x.com/foo.jpg').kind).toBe('image');
  });

  it('EASY-11 — classifies uppercase .JPG as image (case-insensitive)', () => {
    expect(classifyUrl('https://x.com/foo.JPG').kind).toBe('image');
  });

  it('EASY-11 — classifies .jpeg with query string as image', () => {
    expect(classifyUrl('https://x.com/foo.jpeg?v=2').kind).toBe('image');
  });

  it('EASY-11 — classifies .png as image', () => {
    expect(classifyUrl('https://x.com/img.png').kind).toBe('image');
  });

  it('EASY-11 — classifies .gif as image', () => {
    expect(classifyUrl('https://x.com/anim.gif').kind).toBe('image');
  });

  it('EASY-11 — classifies .webp as image', () => {
    expect(classifyUrl('https://x.com/img.webp').kind).toBe('image');
  });

  it('EASY-11 — classifies .svg as image', () => {
    expect(classifyUrl('https://x.com/icon.svg').kind).toBe('image');
  });

  it('EASY-11 — classifies .mp4 as video', () => {
    expect(classifyUrl('https://x.com/clip.mp4').kind).toBe('video');
  });

  it('EASY-11 — classifies .webm as video', () => {
    expect(classifyUrl('https://x.com/clip.webm').kind).toBe('video');
  });

  it('EASY-11 — classifies .mov as video', () => {
    expect(classifyUrl('https://x.com/clip.mov').kind).toBe('video');
  });

  it('classifies YouTube URLs as other, so popups render them as ordinary links', () => {
    for (const url of [
      'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      'https://youtu.be/dQw4w9WgXcQ',
      'https://www.youtube.com/shorts/dQw4w9WgXcQ',
      'https://www.youtube.com/embed/dQw4w9WgXcQ',
      'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ',
    ]) {
      expect(classifyUrl(url)).toEqual({ kind: 'other', srcUrl: url });
    }
  });

  it('EASY-11 — classifies plain URL with no recognized extension as other', () => {
    expect(classifyUrl('https://example.com').kind).toBe('other');
  });

  it('EASY-11 — classifies .html URL as other (not a media extension)', () => {
    expect(classifyUrl('https://x.com/page.html').kind).toBe('other');
  });

  it('EASY-11 — srcUrl for image/video/other is the original URL', () => {
    expect(classifyUrl('https://x.com/foo.jpg').srcUrl).toBe('https://x.com/foo.jpg');
    expect(classifyUrl('https://x.com/foo.mp4').srcUrl).toBe('https://x.com/foo.mp4');
    expect(classifyUrl('https://example.com').srcUrl).toBe('https://example.com');
  });

  it('WR-01 — classifies image URL with trailing period as image (trimTrailingPunctuation applied upstream)', () => {
    // trimTrailingPunctuation strips the trailing dot before classifyUrl sees it
    const cleaned = trimTrailingPunctuation('https://example.com/img.jpg.');
    expect(classifyUrl(cleaned).kind).toBe('image');
  });

});

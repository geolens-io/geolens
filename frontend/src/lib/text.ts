type GraphemeSegmenter = {
  segment(input: string): Iterable<{ segment: string }>;
};

type SegmenterConstructor = new (
  locales?: string | string[],
  options?: { granularity: 'grapheme' },
) => GraphemeSegmenter;

function splitGraphemes(value: string): string[] {
  const Segmenter = (Intl as typeof Intl & { Segmenter?: SegmenterConstructor }).Segmenter;
  if (!Segmenter) return Array.from(value);

  return Array.from(new Segmenter(undefined, { granularity: 'grapheme' }).segment(value), ({ segment }) => segment);
}

export function truncateGraphemes(value: string, maxLength: number, ellipsis = '...'): string {
  if (maxLength < 0) return value;

  const graphemes = splitGraphemes(value);
  if (graphemes.length <= maxLength) return value;

  return `${graphemes.slice(0, maxLength).join('')}${ellipsis}`;
}

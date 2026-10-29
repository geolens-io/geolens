export type MarkdownFormat = 'bold' | 'italic' | 'heading' | 'link' | 'bulletList' | 'numberedList';

interface Edit {
  text: string;
  /** The selection to restore after the edit. */
  start: number;
  end: number;
}

const WRAPS: Partial<Record<MarkdownFormat, [string, string]>> = {
  bold: ['**', '**'],
  italic: ['_', '_'],
  link: ['[', '](https://)'],
};

/**
 * Applies a toolbar format to the selection `start`..`end` of `text`. Bold,
 * italic and link wrap the selection; heading and the lists prefix every line
 * the selection touches.
 */
export function applyMarkdownFormat(
  text: string,
  start: number,
  end: number,
  format: MarkdownFormat,
): Edit {
  const wrap = WRAPS[format];
  if (wrap) {
    const [open, close] = wrap;
    const selected = text.slice(start, end);
    return {
      text: text.slice(0, start) + open + selected + close + text.slice(end),
      start: start + open.length,
      end: end + open.length,
    };
  }
  // A selection ending just after a line break (a triple-click) doesn't take in the next line.
  if (end > start && text[end - 1] === '\n') end -= 1;
  const lineStart = text.lastIndexOf('\n', start - 1) + 1;
  const lines = text.slice(lineStart, end).split('\n');
  const prefixed = lines.map((line, i) =>
    format === 'heading' ? `### ${line}` : format === 'bulletList' ? `- ${line}` : `${i + 1}. ${line}`,
  );
  const block = prefixed.join('\n');
  return {
    text: text.slice(0, lineStart) + block + text.slice(end),
    start: lineStart,
    end: lineStart + block.length,
  };
}

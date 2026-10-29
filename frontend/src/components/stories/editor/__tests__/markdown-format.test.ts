import { applyMarkdownFormat } from '../markdown-format';

describe('applyMarkdownFormat', () => {
  it('wraps the selection in bold and keeps the same words selected', () => {
    const edit = applyMarkdownFormat('a big storm', 2, 5, 'bold');
    expect(edit.text).toBe('a **big** storm');
    expect(edit.text.slice(edit.start, edit.end)).toBe('big');
  });

  it('inserts an empty link at the cursor with the cursor on its text', () => {
    const edit = applyMarkdownFormat('see ', 4, 4, 'link');
    expect(edit.text).toBe('see [](https://)');
    expect(edit.start).toBe(5);
  });

  it('prefixes every line the selection touches for lists and headings', () => {
    const text = 'intro\none\ntwo';
    expect(applyMarkdownFormat(text, 7, 12, 'bulletList').text).toBe('intro\n- one\n- two');
    expect(applyMarkdownFormat(text, 7, 12, 'numberedList').text).toBe('intro\n1. one\n2. two');
    expect(applyMarkdownFormat(text, 2, 2, 'heading').text).toBe('### intro\none\ntwo');
  });
});

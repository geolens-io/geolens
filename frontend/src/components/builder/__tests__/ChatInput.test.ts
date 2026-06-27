import { detectTrigger, computeMentionInsertion, type TriggerState } from '../ChatInput';

// builder-audit TEST-01: the @-mention / slash-command parsing was previously
// untested. detectTrigger uses cursor-sliced regex and computeMentionInsertion
// does bracket-syntax insertion with +1-for-trigger-char offset arithmetic —
// both are off-by-one-prone.

describe('detectTrigger', () => {
  it('detects an @ trigger at the start of the input', () => {
    expect(detectTrigger('@par', 4)).toEqual({ type: '@', startIndex: 0, query: 'par' });
  });

  it('detects an @ trigger after whitespace', () => {
    const value = 'filter @par';
    expect(detectTrigger(value, value.length)).toEqual({ type: '@', startIndex: 7, query: 'par' });
  });

  it('returns the bare @ with an empty query', () => {
    expect(detectTrigger('@', 1)).toEqual({ type: '@', startIndex: 0, query: '' });
  });

  it('detects a / trigger at the start of the input', () => {
    expect(detectTrigger('/sty', 4)).toEqual({ type: '/', startIndex: 0, query: 'sty' });
  });

  it('detects a / trigger after whitespace', () => {
    const value = 'do /fil';
    expect(detectTrigger(value, value.length)).toEqual({ type: '/', startIndex: 3, query: 'fil' });
  });

  it('suppresses an @ that is glued to a preceding word character (email mid-word)', () => {
    // "user@" — the @ is preceded by a word char, so it is NOT a mention trigger.
    expect(detectTrigger('user@x', 6)).toBeNull();
  });

  it('suppresses a / that is mid-word (path segment)', () => {
    expect(detectTrigger('a/b', 3)).toBeNull();
  });

  it('returns null when there is no trigger before the cursor', () => {
    expect(detectTrigger('hello world', 11)).toBeNull();
  });

  it('uses the cursor position, not the end of the string', () => {
    // Cursor sits right after "@pa"; the trailing "rk extra" is ignored.
    expect(detectTrigger('@park extra', 3)).toEqual({ type: '@', startIndex: 0, query: 'pa' });
  });

  it('ignores a completed mention once whitespace follows it', () => {
    const value = '@park ';
    expect(detectTrigger(value, value.length)).toBeNull();
  });
});

describe('computeMentionInsertion', () => {
  const atTrigger = (startIndex: number, query: string): TriggerState => ({ type: '@', startIndex, query });
  const slashTrigger = (startIndex: number, query: string): TriggerState => ({ type: '/', startIndex, query });

  it('inserts a plain @Name (no spaces) and trailing space, cursor after the space', () => {
    const result = computeMentionInsertion('@par', atTrigger(0, 'par'), { label: 'Parks' });
    expect(result.value).toBe('@Parks ');
    expect(result.cursor).toBe('@Parks '.length);
  });

  it('uses bracket syntax for labels containing a space', () => {
    const result = computeMentionInsertion('@cit', atTrigger(0, 'cit'), { label: 'City Limits' });
    expect(result.value).toBe('@[City Limits] ');
    expect(result.cursor).toBe('@[City Limits] '.length);
  });

  it('preserves text before and after the trigger token', () => {
    const value = 'show @par on map';
    // trigger spans indices 5.."@par" (query 'par', startIndex 5); text after is ' on map'
    const result = computeMentionInsertion(value, atTrigger(5, 'par'), { label: 'Parks' });
    expect(result.value).toBe('show @Parks  on map');
    // cursor lands right after the inserted "@Parks " (before the original ' on map')
    expect(result.cursor).toBe('show @Parks '.length);
  });

  it('inserts a slash command label followed by a space (no bracketing)', () => {
    const result = computeMentionInsertion('/fil', slashTrigger(0, 'fil'), { label: '/filter' });
    expect(result.value).toBe('/filter ');
    expect(result.cursor).toBe('/filter '.length);
  });

  it('replaces the typed query, not just appends, using the +1 trigger-char offset', () => {
    // value '@xyz' with query 'xyz' → after-slice starts at startIndex+1+3 = 4 (end),
    // so the whole '@xyz' is replaced by the chosen item.
    const result = computeMentionInsertion('@xyz', atTrigger(0, 'xyz'), { label: 'Roads' });
    expect(result.value).toBe('@Roads ');
  });
});

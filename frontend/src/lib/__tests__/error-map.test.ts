import { summarizeErrorDetail } from '@/lib/error-map';

/**
 * fix(#435): UX-03 — an unintercepted 422 used to put a raw array of Pydantic
 * error objects into a toast. These assert that no branch can return JSON.
 */
describe('summarizeErrorDetail', () => {
  it('passes a string detail through unchanged', () => {
    expect(summarizeErrorDetail('Dataset not found', 'fallback')).toBe('Dataset not found');
  });

  it("takes the first entry's msg from a FastAPI 422 array", () => {
    const detail = [
      { type: 'missing', loc: ['body', 'name'], msg: 'Field required', input: {} },
      { type: 'string_type', loc: ['body', 'srid'], msg: 'Input should be a valid string' },
    ];
    expect(summarizeErrorDetail(detail, 'fallback')).toBe('Field required');
  });

  it('skips malformed leading entries to find a usable msg', () => {
    const detail = [{ type: 'missing' }, null, { msg: 'Field required' }];
    expect(summarizeErrorDetail(detail, 'fallback')).toBe('Field required');
  });

  it('reads msg off a bare object detail', () => {
    expect(summarizeErrorDetail({ msg: 'Too many requests' }, 'fallback')).toBe('Too many requests');
  });

  it('falls back rather than leaking JSON for an unrecognized object', () => {
    expect(summarizeErrorDetail({ code: 17, ctx: { limit: 3 } }, 'Bad Request')).toBe('Bad Request');
  });

  it('falls back rather than leaking JSON for an array with no msg', () => {
    expect(summarizeErrorDetail([{ code: 17 }], 'Bad Request')).toBe('Bad Request');
  });

  it('falls back for an empty array', () => {
    expect(summarizeErrorDetail([], 'Bad Request')).toBe('Bad Request');
  });

  it('ignores a non-string msg', () => {
    expect(summarizeErrorDetail([{ msg: 42 }], 'Bad Request')).toBe('Bad Request');
  });

  it('ignores an empty-string msg', () => {
    expect(summarizeErrorDetail([{ msg: '' }], 'Bad Request')).toBe('Bad Request');
  });

  it('never returns a value that parses as JSON structure', () => {
    const nasty = [{ type: 'missing', loc: ['body'], msg: 'Field required' }];
    const result = summarizeErrorDetail(nasty, 'fallback');
    expect(result).not.toContain('{');
    expect(result).not.toContain('[');
  });
});

import {
  buildZoomExpression,
  isSupportedZoomExpression,
  parseZoomExpression,
  validateZoomExpressionDraft,
} from '../zoom-expressions';

describe('zoom expression helpers', () => {
  it('parses supported step expressions into editable stops', () => {
    expect(parseZoomExpression(['step', ['zoom'], 1, 8, 2, 12, 4])).toEqual({
      kind: 'step',
      baseValue: 1,
      stops: [
        { zoom: 8, value: 2 },
        { zoom: 12, value: 4 },
      ],
    });
  });

  it('parses supported interpolate expressions into editable stops', () => {
    expect(parseZoomExpression(['interpolate', ['linear'], ['zoom'], 4, 1, 10, 3, 16, 8])).toEqual({
      kind: 'interpolate',
      stops: [
        { zoom: 4, value: 1 },
        { zoom: 10, value: 3 },
        { zoom: 16, value: 8 },
      ],
    });
  });

  it('rejects composite and data-driven expressions', () => {
    expect(parseZoomExpression(['step', ['get', 'population'], 1, 8, 2])).toBeNull();
    expect(parseZoomExpression(['interpolate', ['linear'], ['zoom'], 4, ['get', 'width'], 10, 3])).toBeNull();
    expect(parseZoomExpression(['interpolate', ['linear'], ['zoom'], 4, 1, 10, ['get', 'width']])).toBeNull();
  });

  it('reports validation errors for malformed stop drafts', () => {
    expect(validateZoomExpressionDraft({ kind: 'interpolate', stops: [{ zoom: 4, value: 1 }] }).errors).toContain(
      'Interpolate expressions need at least two zoom stops.',
    );
    expect(validateZoomExpressionDraft({ kind: 'step', baseValue: 1, stops: [{ zoom: 12, value: 4 }, { zoom: 8, value: 2 }] }).errors).toContain(
      'Zoom stops must be in ascending order.',
    );
    expect(validateZoomExpressionDraft({ kind: 'step', stops: [{ zoom: Number.NaN, value: 2 }] }).errors).toEqual(
      expect.arrayContaining([
        'Step expressions need a numeric base value.',
        'Stop 1 needs a numeric zoom.',
      ]),
    );
  });

  it('round-trips supported expressions through parse and build', () => {
    const step = ['step', ['zoom'], 1, 8, 2, 12, 4] as const;
    const interpolate = ['interpolate', ['linear'], ['zoom'], 4, 1, 10, 3, 16, 8] as const;

    expect(buildZoomExpression(parseZoomExpression(step) ?? fail('step should parse'))).toEqual(step);
    expect(buildZoomExpression(parseZoomExpression(interpolate) ?? fail('interpolate should parse'))).toEqual(interpolate);
  });

  it('identifies supported zoom expressions', () => {
    expect(isSupportedZoomExpression(['step', ['zoom'], 1, 8, 2])).toBe(true);
    expect(isSupportedZoomExpression(['step', ['get', 'value'], 1, 8, 2])).toBe(false);
  });
});

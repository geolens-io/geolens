import type { ZoomExpression, ZoomExpressionKind } from '@/types/api';

export type { ZoomExpression, ZoomExpressionKind } from '@/types/api';

export interface ZoomStop {
  zoom: number;
  value: number;
}

export interface ZoomExpressionDraft {
  kind: ZoomExpressionKind;
  baseValue?: number;
  stops: ZoomStop[];
}

export interface ZoomExpressionValidationResult {
  ok: boolean;
  errors: string[];
}

// builder-audit DRY-03: exported so ZoomExpressionEditor imports this one copy
// instead of redefining an identical local guard.
export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * builder-audit DRY-04: shared low-level pair walker for the `[..., a0, b0, a1,
 * b1, ...]` tail of step / interpolate / line-gradient expressions. Zips from
 * `startIndex` in steps of 2 and returns one entry per first-element; `hasSecond`
 * is false for a dangling final element (odd-length tail).
 *
 * It intentionally applies NO number-check, no early-break, and no
 * drop-first/keep-all stop semantics — each caller layers its own validation and
 * stop convention on top (parseStepOrInterpolate drops the first interpolate stop
 * as the "< X" bucket; parseZoomExpression and lineGradientExpressionToStops keep
 * all stops). This keeps the three walkers in sync without flattening their
 * deliberately-different domain semantics.
 */
export interface ExpressionPair {
  first: unknown;
  second: unknown;
  hasSecond: boolean;
}

export function walkExpressionPairs(expr: readonly unknown[], startIndex: number): ExpressionPair[] {
  const pairs: ExpressionPair[] = [];
  for (let i = startIndex; i < expr.length; i += 2) {
    const hasSecond = i + 1 < expr.length;
    pairs.push({ first: expr[i], second: hasSecond ? expr[i + 1] : undefined, hasSecond });
  }
  return pairs;
}

function isZoomInput(value: unknown): value is ['zoom'] {
  return Array.isArray(value) && value.length === 1 && value[0] === 'zoom';
}

function isLinearInterpolation(value: unknown): value is ['linear'] {
  return Array.isArray(value) && value.length === 1 && value[0] === 'linear';
}

function allNumbers(values: unknown[]): values is number[] {
  return values.every(isFiniteNumber);
}

function pairsToStops(values: number[]): ZoomStop[] {
  // DRY-04: keep-all stop semantics over the shared pair walker. `values` is
  // already validated (even length, all finite numbers) by the caller.
  return walkExpressionPairs(values, 0).map((pair) => ({
    zoom: pair.first as number,
    value: pair.second as number,
  }));
}

export function parseZoomExpression(value: unknown): ZoomExpressionDraft | null {
  if (!Array.isArray(value)) return null;

  if (value[0] === 'step') {
    const [, input, baseValue, ...rawStops] = value;
    if (!isZoomInput(input) || !isFiniteNumber(baseValue)) return null;
    if (rawStops.length === 0 || rawStops.length % 2 !== 0 || !allNumbers(rawStops)) return null;
    const draft: ZoomExpressionDraft = {
      kind: 'step',
      baseValue,
      stops: pairsToStops(rawStops),
    };
    return validateZoomExpressionDraft(draft).ok ? draft : null;
  }

  if (value[0] === 'interpolate') {
    const [, interpolation, input, ...rawStops] = value;
    if (!isLinearInterpolation(interpolation) || !isZoomInput(input)) return null;
    if (rawStops.length === 0 || rawStops.length % 2 !== 0 || !allNumbers(rawStops)) return null;
    const draft: ZoomExpressionDraft = {
      kind: 'interpolate',
      stops: pairsToStops(rawStops),
    };
    return validateZoomExpressionDraft(draft).ok ? draft : null;
  }

  return null;
}

export function isSupportedZoomExpression(value: unknown): value is ZoomExpression {
  return parseZoomExpression(value) !== null;
}

export function validateZoomExpressionDraft(draft: ZoomExpressionDraft): ZoomExpressionValidationResult {
  const errors: string[] = [];
  const minStops = draft.kind === 'step' ? 1 : 2;

  if (draft.kind !== 'step' && draft.kind !== 'interpolate') {
    errors.push('Choose a supported zoom expression type.');
  }

  if (draft.kind === 'step' && !isFiniteNumber(draft.baseValue)) {
    errors.push('Step expressions need a numeric base value.');
  }

  if (draft.stops.length < minStops) {
    errors.push(
      draft.kind === 'step'
        ? 'Step expressions need at least one zoom stop.'
        : 'Interpolate expressions need at least two zoom stops.',
    );
  }

  draft.stops.forEach((stop, index) => {
    if (!isFiniteNumber(stop.zoom)) {
      errors.push(`Stop ${index + 1} needs a numeric zoom.`);
    }
    if (!isFiniteNumber(stop.value)) {
      errors.push(`Stop ${index + 1} needs a numeric value.`);
    }
    if (index > 0 && isFiniteNumber(stop.zoom) && isFiniteNumber(draft.stops[index - 1]?.zoom) && stop.zoom <= draft.stops[index - 1].zoom) {
      errors.push('Zoom stops must be in ascending order.');
    }
  });

  return { ok: errors.length === 0, errors };
}

export function buildZoomExpression(draft: ZoomExpressionDraft): ZoomExpression {
  const validation = validateZoomExpressionDraft(draft);
  if (!validation.ok) {
    throw new Error(validation.errors.join(' '));
  }

  if (draft.kind === 'step') {
    return [
      'step',
      ['zoom'],
      draft.baseValue as number,
      ...draft.stops.flatMap((stop) => [stop.zoom, stop.value]),
    ] as ZoomExpression;
  }

  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    ...draft.stops.flatMap((stop) => [stop.zoom, stop.value]),
  ] as ZoomExpression;
}

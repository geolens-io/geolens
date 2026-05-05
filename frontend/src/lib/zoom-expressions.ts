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

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
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
  const stops: ZoomStop[] = [];
  for (let index = 0; index < values.length; index += 2) {
    stops.push({ zoom: values[index], value: values[index + 1] });
  }
  return stops;
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

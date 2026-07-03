import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X, Code } from 'lucide-react';
import type { FilterSpecification } from 'maplibre-gl';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  buildNullableSafeNumericAccessor,
  parseCanonicalFilter,
  validateRawFilter,
  FilterValidationError,
  NUMERIC_COMPARISON_OPERATORS,
} from '@/lib/maplibre-filter-utils';

interface FilterCondition {
  id: string;
  field: string;
  operator: string;
  value: string;
}

interface LayerFilterEditorProps {
  columnInfo: { name: string; type: string }[];
  filter: FilterSpecification | null;
  onFilterChange: (expression: FilterSpecification | null) => void;
  layerName?: string | null;
  /**
   * EASY-18 (Phase 1138-03): rendered-feature count for this layer. When set
   * to 0 AND `filter` is non-null, the empty-state hint + Clear-filter button
   * are shown. `null` / `undefined` (default) suppresses the hint regardless
   * of filter state.
   */
  featureCount?: number | null;
}

type ColumnType = 'string' | 'number' | 'boolean' | 'other';

interface OperatorDef {
  label?: string;
  labelKey?: string;
  value: string;
}

// builder-audit #338 DRY-02: NUMERIC_COMPARISON_OPERATORS now imported from
// maplibre-filter-utils (the single canonical copy) instead of re-declared here.

// Discriminated union returned by parseFilterExpression
export type ParseResult =
  | { kind: 'editable'; combinator: 'all' | 'any'; conditions: FilterCondition[] }
  | { kind: 'opaque'; raw: FilterSpecification };

function classifyColumnType(pgType: string): ColumnType {
  const t = pgType.toLowerCase();
  if (/int|float|double|numeric|real|decimal/.test(t)) return 'number';
  if (/boolean|bool/.test(t)) return 'boolean';
  if (/text|varchar|char|string/.test(t)) return 'string';
  return 'other';
}

const OPERATORS_BY_TYPE: Record<ColumnType, OperatorDef[]> = {
  string: [
    { labelKey: 'filters.operators.equals', value: '==' },
    { labelKey: 'filters.operators.notEquals', value: '!=' },
    { labelKey: 'filters.operators.contains', value: 'contains' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
    { value: 'in_list', labelKey: 'filters.operators.inList' },
    { value: 'not_in_list', labelKey: 'filters.operators.notInList' },
    { value: 'has', labelKey: 'filters.operators.exists' },
  ],
  number: [
    { label: '=', value: '==' },
    { label: '!=', value: '!=' },
    { label: '>', value: '>' },
    { label: '<', value: '<' },
    { label: '>=', value: '>=' },
    { label: '<=', value: '<=' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
    { value: 'in_list', labelKey: 'filters.operators.inList' },
    { value: 'not_in_list', labelKey: 'filters.operators.notInList' },
    { value: 'has', labelKey: 'filters.operators.exists' },
  ],
  boolean: [
    { labelKey: 'filters.operators.equals', value: '==' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
    { value: 'has', labelKey: 'filters.operators.exists' },
  ],
  other: [
    { labelKey: 'filters.operators.equals', value: '==' },
    { labelKey: 'filters.operators.notEquals', value: '!=' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
  ],
};

function coerceValue(value: string, pgType: string): string | number | boolean {
  const colType = classifyColumnType(pgType);
  if (colType === 'number') {
    if (value === '') return '';
    const n = Number(value);
    return isNaN(n) ? value : n;
  }
  if (colType === 'boolean') {
    return value.toLowerCase() === 'true';
  }
  return value;
}

export function buildFilterExpression(
  conditions: FilterCondition[],
  columnInfo: { name: string; type: string }[],
  combinator: 'all' | 'any' = 'all',
): FilterSpecification | null {
  const valid = conditions.filter((c) => {
    if (!c.field || !c.operator) return false;
    if (c.operator === 'is_null' || c.operator === 'has') return true;
    if (c.value === '' || c.value === undefined || c.value === null) return false;
    // Reject non-numeric values for numeric columns
    const col = columnInfo.find((ci) => ci.name === c.field);
    const isNumeric = !!col && classifyColumnType(col.type) === 'number';
    // fix(#394) FL-03: list operators validate PER ENTRY — the whole-string
    // NaN check below would reject every numeric list ("1,2" → Number NaN);
    // the condition stays valid while at least one entry is numeric, and the
    // emit branch drops the non-numeric entries.
    if (isNumeric && (c.operator === 'in_list' || c.operator === 'not_in_list')) {
      return String(c.value)
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean)
        .some((v) => !isNaN(Number(v)));
    }
    if (isNumeric && isNaN(Number(c.value))) return false;
    return true;
  });
  if (valid.length === 0) return null;

  const expressions: unknown[] = [];

  for (const cond of valid) {
    const col = columnInfo.find((c) => c.name === cond.field);
    const pgType = col?.type ?? 'text';

    if (cond.operator === 'is_null') {
      expressions.push(['any', ['!', ['has', cond.field]], ['==', ['get', cond.field], null]]);
    } else if (cond.operator === 'has') {
      expressions.push(['has', cond.field]);
    } else if (cond.operator === 'in_list' || cond.operator === 'not_in_list') {
      const values = String(cond.value).split(',').map(v => v.trim()).filter(Boolean);
      // fix(#394) FL-03: per-entry NaN guard for numeric columns — coerceValue
      // leaves non-numeric entries as strings, so "1,abc,3" silently emitted a
      // mixed-type literal. Drop the entries that don't coerce instead.
      const numericColumn = classifyColumnType(pgType) === 'number';
      const coerced = values
        .map(v => coerceValue(v, pgType))
        .filter(v => !numericColumn || typeof v === 'number');
      const inExpr = ['in', ['get', cond.field], ['literal', coerced]];
      expressions.push(cond.operator === 'in_list' ? inExpr : ['!', inExpr]);
    } else if (cond.operator === 'contains') {
      expressions.push(['in', cond.value.trim(), ['get', cond.field]]);
    } else {
      const coerced = coerceValue(cond.value, pgType);
      const isNumericComparison =
        classifyColumnType(pgType) === 'number' &&
        typeof coerced === 'number' &&
        NUMERIC_COMPARISON_OPERATORS.has(cond.operator);
      expressions.push([
        cond.operator,
        isNumericComparison
          ? buildNullableSafeNumericAccessor(cond.field, cond.operator, coerced)
          : ['get', cond.field],
        coerced,
      ]);
    }
  }

  // Always wrap to preserve combinator intent on round-trip
  return [combinator, ...expressions] as FilterSpecification;
}

export function parseFilterExpression(expr: FilterSpecification | null): ParseResult {
  // builder-audit #338 DRY-01/FILT-01/FILT-02: delegate all filter recognition to the
  // single canonical parser in maplibre-filter-utils so the structured editor and
  // ActiveFilterChips cannot drift again. We only re-attach editor-local row ids.
  const canonical = parseCanonicalFilter(expr);
  if (canonical.kind === 'opaque') {
    return { kind: 'opaque', raw: canonical.raw };
  }
  return {
    kind: 'editable',
    combinator: canonical.combinator,
    conditions: canonical.conditions.map((c) => ({
      id: crypto.randomUUID(),
      field: c.field,
      operator: c.operator,
      value: c.value,
    })),
  };
}

export function LayerFilterEditor({
  columnInfo,
  filter,
  onFilterChange,
  layerName,
  featureCount,
}: LayerFilterEditorProps) {
  const { t } = useTranslation('builder');
  const lastEmittedFilterRef = useRef<unknown>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [conditions, setConditions] = useState<FilterCondition[]>([]);
  const [combinator, setCombinator] = useState<'all' | 'any'>('all');
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState('');
  const [rawError, setRawError] = useState<string | null>(null);
  const [opaque, setOpaque] = useState(false);

  function applyParseResult(result: ParseResult) {
    if (result.kind === 'opaque') {
      setOpaque(true);
      setRawMode(true);
      setRawText(JSON.stringify(result.raw, null, 2));
      setConditions([]);
    } else {
      setOpaque(false);
      setConditions(result.conditions);
      setCombinator(result.combinator);
    }
  }

  // Sync from filter prop when it changes externally (not from our own emit)
  useEffect(() => {
    if (filter === lastEmittedFilterRef.current) return;
    const result = parseFilterExpression(filter);
    applyParseResult(result);
  }, [filter]);

  function getFieldType(fieldName: string): ColumnType {
    const col = columnInfo.find((c) => c.name === fieldName);
    return col ? classifyColumnType(col.type) : 'other';
  }

  // Phase 20260526-builder-audit #338 BLD-20260526-11: cleanup debounce timer on unmount.
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  function emitChange(updated: FilterCondition[], combo: 'all' | 'any' = combinator) {
    setConditions(updated);
    const newFilter = buildFilterExpression(updated, columnInfo, combo);
    lastEmittedFilterRef.current = newFilter;
    onFilterChange(newFilter);
  }

  // Phase 20260526-builder-audit #338 BLD-20260526-11: debounced version for value input keystrokes.
  const debouncedEmit = useCallback(
    (updated: FilterCondition[], combo: 'all' | 'any') => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      setConditions(updated);
      debounceTimerRef.current = setTimeout(() => {
        const newFilter = buildFilterExpression(updated, columnInfo, combo);
        lastEmittedFilterRef.current = newFilter;
        onFilterChange(newFilter);
      }, 200);
    },
    [columnInfo, onFilterChange],
  );

  function addCondition() {
    const field = columnInfo[0]?.name ?? '';
    const operator = OPERATORS_BY_TYPE[getFieldType(field)][0]?.value ?? '==';
    const newCond: FilterCondition = {
      id: crypto.randomUUID(),
      field,
      operator,
      value: getFieldType(field) === 'boolean' && operator === '==' ? 'true' : '',
    };
    emitChange([...conditions, newCond]);
  }

  function removeCondition(id: string) {
    emitChange(conditions.filter((c) => c.id !== id));
  }

  function updateCondition(id: string, patch: Partial<FilterCondition>, debounce = false) {
    const updated = conditions.map((c) => {
      if (c.id !== id) return c;
      const merged = { ...c, ...patch };

      // If field changed, reset operator and value
      if (patch.field && patch.field !== c.field) {
        const colType = getFieldType(patch.field);
        const ops = OPERATORS_BY_TYPE[colType];
        merged.operator = ops[0]?.value ?? '==';
        merged.value = colType === 'boolean' && merged.operator === '==' ? 'true' : '';
      }

      if (patch.operator && patch.operator !== c.operator) {
        const colType = getFieldType(merged.field);
        if (colType === 'boolean' && patch.operator === '==' && !merged.value) {
          merged.value = 'true';
        }
      }

      return merged;
    });
    if (debounce) {
      debouncedEmit(updated, combinator);
    } else {
      emitChange(updated);
    }
  }

  function handleCombinatorChange(value: string) {
    const combo = value as 'all' | 'any';
    setCombinator(combo);
    const newFilter = buildFilterExpression(conditions, columnInfo, combo);
    lastEmittedFilterRef.current = newFilter;
    onFilterChange(newFilter);
  }

  function handleRawModeToggle() {
    if (!rawMode) {
      // Entering raw mode: serialize current filter
      const current = buildFilterExpression(conditions, columnInfo, combinator);
      setRawText(current ? JSON.stringify(current, null, 2) : '');
      setRawError(null);
    } else {
      // Exiting raw mode: re-parse current filter
      if (!opaque) {
        setRawError(null);
      }
    }
    setRawMode((prev) => !prev);
  }

  function handleRawApply() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawText);
    } catch {
      setRawError(t('filters.rawJsonError'));
      return;
    }
    if (parsed !== null && !Array.isArray(parsed)) {
      setRawError(t('filters.rawJsonError'));
      return;
    }

    // builder-audit #338 P1-04: validate + normalize against the shared filter grammar
    // (mirrors backend validate_filter) so invalid arity / unsupported legacy
    // forms are rejected here instead of being saved and surfacing late as a
    // MapLibre setFilter error. Opaque-but-valid filters are preserved verbatim.
    let normalized: FilterSpecification | null;
    try {
      normalized = validateRawFilter(parsed);
    } catch (e) {
      setRawError(
        e instanceof FilterValidationError
          ? t('filters.rawFilterInvalid')
          : t('filters.rawJsonError'),
      );
      return;
    }

    // EDIT-03: null / empty-array both clear the filter (validateRawFilter maps []
    // to null) so map.setFilter(id, []) can never be reached. Reset editor state.
    if (normalized === null) {
      lastEmittedFilterRef.current = null;
      onFilterChange(null);
      applyParseResult(parseFilterExpression(null));
      setRawError(null);
      return;
    }

    lastEmittedFilterRef.current = normalized;
    onFilterChange(normalized);
    applyParseResult(parseFilterExpression(normalized));
    setRawError(null);
  }

  function handleEnableRawMode() {
    setRawMode(true);
    setRawText(filter ? JSON.stringify(filter, null, 2) : '');
    setRawError(null);
  }

  // EASY-18: show empty-state hint when a filter is set but no features rendered.
  const showEmptyState = filter != null && featureCount === 0;

  return (
    <div className="space-y-3 rounded-md border bg-muted/30 p-3">
      {/* EASY-18: empty-state hint — shown when filter is active but 0 features rendered.
          fix(#394) FL-02: the count is VIEWPORT-scoped (queryRenderedFeatures), so
          the copy says "in view" — matches may exist off-screen and "eliminated
          every feature" was a false alarm in that case. */}
      {showEmptyState && (
        <div
          role="status"
          aria-live="polite"
          className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 p-3"
        >
          <p className="text-xs font-semibold text-foreground">
            {t('layerEditor.emptyResult.title', { defaultValue: '0 features in view — check your filter' })}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {t('layerEditor.emptyResult.help', {
              defaultValue:
                'The current filter matches nothing in the visible map area. Matches may exist off-screen — pan or zoom out, adjust a condition, or clear the filter.',
            })}
          </p>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="mt-2"
            onClick={() => onFilterChange(null)}
          >
            {t('layerEditor.emptyResult.clear', { defaultValue: 'Clear filter' })}
          </Button>
        </div>
      )}
      {/* Header row: title + raw toggle */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <div className="text-xs font-medium">{t('filters.layerTitle')}</div>
          <p className="text-[11px] leading-snug text-muted-foreground">
            {t('filters.scopeHelp', { layer: layerName ?? t('filters.thisLayer') })}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-xs text-muted-foreground"
          onClick={handleRawModeToggle}
          title={t('filters.rawJson')}
        >
          <Code className="h-3 w-3 me-1" />
          {t('filters.rawJson')}
        </Button>
      </div>

      {rawMode ? (
        /* Raw JSON editing mode */
        <div className="space-y-2">
          <textarea
            className="w-full rounded border border-input bg-background p-2 text-xs font-mono resize-y min-h-[100px] outline-none focus:ring-1 focus:ring-ring"
            value={rawText}
            onChange={(e) => {
              setRawText(e.target.value);
              setRawError(null);
            }}
            spellCheck={false}
          />
          {rawError && (
            <div className="text-xs text-destructive">{rawError}</div>
          )}
          <Button size="sm" className="h-7 text-xs" onClick={handleRawApply}>
            {t('filters.rawJsonApply')}
          </Button>
        </div>
      ) : opaque ? (
        /* Opaque banner — cannot edit visually */
        <div className="rounded bg-muted p-2 text-xs text-muted-foreground space-y-2">
          <p>{t('filters.opaqueWarning')}</p>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleEnableRawMode}
          >
            <Code className="h-3 w-3 me-1" />
            {t('filters.rawJson')}
          </Button>
        </div>
      ) : (
        /* Visual editing mode */
        <>
          {columnInfo.length === 0 && (
            <p className="rounded-md bg-muted px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">
              {t('filters.noColumns')}
            </p>
          )}
          {/* Combinator select */}
          <Select value={combinator} onValueChange={handleCombinatorChange} aria-label={t('filters.combinator', { defaultValue: 'Match condition' })}>
            <SelectTrigger className="h-7 text-xs w-44" aria-label={t('filters.combinator', { defaultValue: 'Match condition' })}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">
                {t('filters.matchAll')}
              </SelectItem>
              <SelectItem value="any" className="text-xs">
                {t('filters.matchAny')}
              </SelectItem>
            </SelectContent>
          </Select>

          {conditions.map((cond) => {
            const colType = getFieldType(cond.field);
            const ops = OPERATORS_BY_TYPE[colType];

            return (
              <div key={cond.id} data-testid="filter-condition-row" className="space-y-1.5">
                {/* Field select */}
                <div data-testid="filter-field-row" className="min-w-0">
                  <Select
                    value={cond.field}
                    onValueChange={(val) => updateCondition(cond.id, { field: val })}
                    aria-label={t('filters.field')}
                  >
                    <SelectTrigger className="h-7 w-full min-w-0 text-xs" aria-label={t('filters.field')}>
                      <SelectValue placeholder={t('filters.field')} />
                    </SelectTrigger>
                    <SelectContent>
                      {columnInfo.map((col) => (
                        <SelectItem key={col.name} value={col.name} className="text-xs">
                          {col.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div data-testid="filter-value-row" className="grid grid-cols-[minmax(5rem,6.5rem)_minmax(0,1fr)_1.75rem] items-center gap-1.5">
                  {/* Operator select */}
                  <Select
                    value={cond.operator}
                    onValueChange={(val) => updateCondition(cond.id, { operator: val })}
                    aria-label={t('filters.op')}
                  >
                    <SelectTrigger className="h-7 w-full text-xs" aria-label={t('filters.op')}>
                      <SelectValue placeholder={t('filters.op')} />
                    </SelectTrigger>
                    <SelectContent>
                      {ops.map((op) => (
                        <SelectItem key={op.value} value={op.value} className="text-xs">
                          {op.labelKey ? t(op.labelKey) : op.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {/* Value input (hidden for is_null and has) */}
                  {cond.operator !== 'is_null' && cond.operator !== 'has' ? (
                    getFieldType(cond.field) === 'boolean' && cond.operator === '==' ? (
                      <Select
                        value={cond.value || 'true'}
                        onValueChange={(val) => updateCondition(cond.id, { value: val })}
                      >
                        <SelectTrigger className="h-7 w-full text-xs" aria-label={t('filters.value')}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="true" className="text-xs">true</SelectItem>
                          <SelectItem value="false" className="text-xs">false</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        className="h-7 w-full min-w-0 text-xs"
                        placeholder={t('filters.value')}
                        aria-label={t('filters.value')}
                        value={cond.value}
                        onChange={(e) => updateCondition(cond.id, { value: e.target.value }, true)}
                      />
                    )
                  ) : (
                    <span aria-hidden="true" />
                  )}

                  {/* Remove button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0 justify-self-end"
                    onClick={() => removeCondition(cond.id)}
                    aria-label={t('filters.removeCondition', { defaultValue: 'Remove condition' })}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            );
          })}

          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={addCondition}>
            <Plus className="h-3 w-3 me-1" />
            {t('filters.addFilter')}
          </Button>
        </>
      )}
    </div>
  );
}

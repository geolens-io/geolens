import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X, Code } from 'lucide-react';
import type { FilterSpecification } from 'maplibre-gl';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

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
}

type ColumnType = 'string' | 'number' | 'boolean' | 'other';

interface OperatorDef {
  label?: string;
  labelKey?: string;
  value: string;
}

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
    if (col && classifyColumnType(col.type) === 'number' && isNaN(Number(c.value))) return false;
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
    } else if (cond.operator === 'in_list') {
      const values = String(cond.value).split(',').map(v => v.trim()).filter(Boolean);
      const coerced = values.map(v => coerceValue(v, pgType));
      expressions.push(['in', ['get', cond.field], ['literal', coerced]]);
    } else if (cond.operator === 'not_in_list') {
      const values = String(cond.value).split(',').map(v => v.trim()).filter(Boolean);
      const coerced = values.map(v => coerceValue(v, pgType));
      expressions.push(['!', ['in', ['get', cond.field], ['literal', coerced]]]);
    } else if (cond.operator === 'contains') {
      expressions.push(['in', cond.value.trim(), ['get', cond.field]]);
    } else {
      const coerced = coerceValue(cond.value, pgType);
      expressions.push([cond.operator, ['get', cond.field], coerced]);
    }
  }

  // Always wrap to preserve combinator intent on round-trip
  return [combinator, ...expressions] as FilterSpecification;
}

export function parseFilterExpression(expr: FilterSpecification | null): ParseResult {
  if (!expr || !Array.isArray(expr) || expr.length === 0) {
    return { kind: 'editable', combinator: 'all', conditions: [] };
  }

  function parseSingle(e: unknown[]): FilterCondition | null {
    if (!Array.isArray(e) || e.length === 0) return null;

    // B-001: is_null full pattern: ["any", ["!", ["has", f]], ["==", ["get", f], null]]
    if (
      e[0] === 'any' &&
      e.length === 3 &&
      Array.isArray(e[1]) && e[1][0] === '!' && Array.isArray(e[1][1]) && e[1][1][0] === 'has' &&
      Array.isArray(e[2]) && e[2][0] === '==' && Array.isArray(e[2][1]) && e[2][1][0] === 'get' && e[2][2] === null &&
      e[1][1][1] === e[2][1][1]
    ) {
      return {
        id: crypto.randomUUID(),
        field: e[1][1][1] as string,
        operator: 'is_null',
        value: '',
      };
    }

    // is_null: ["!", ["has", field]] (legacy/short form)
    if (e[0] === '!' && Array.isArray(e[1]) && e[1][0] === 'has') {
      return {
        id: crypto.randomUUID(),
        field: e[1][1] as string,
        operator: 'is_null',
        value: '',
      };
    }

    // B-002: not_in_list: ["!", ["in", ["get", f], ["literal", [...]]]]
    if (
      e[0] === '!' &&
      Array.isArray(e[1]) && e[1][0] === 'in' &&
      Array.isArray(e[1][1]) && e[1][1][0] === 'get' &&
      Array.isArray(e[1][2]) && e[1][2][0] === 'literal'
    ) {
      return {
        id: crypto.randomUUID(),
        field: e[1][1][1] as string,
        operator: 'not_in_list',
        value: (e[1][2][1] as unknown[]).join(', '),
      };
    }

    // B-002: in_list: ["in", ["get", f], ["literal", [...]]]
    if (
      e[0] === 'in' &&
      Array.isArray(e[1]) && e[1][0] === 'get' &&
      Array.isArray(e[2]) && e[2][0] === 'literal'
    ) {
      return {
        id: crypto.randomUUID(),
        field: e[1][1] as string,
        operator: 'in_list',
        value: (e[2][1] as unknown[]).join(', '),
      };
    }

    // contains: ["in", value, ["get", field]]
    if (e[0] === 'in' && Array.isArray(e[2]) && e[2][0] === 'get') {
      return {
        id: crypto.randomUUID(),
        field: e[2][1] as string,
        operator: 'contains',
        value: String(e[1]),
      };
    }

    // B-003: has: ["has", field]
    if (e[0] === 'has' && typeof e[1] === 'string') {
      return {
        id: crypto.randomUUID(),
        field: e[1],
        operator: 'has',
        value: '',
      };
    }

    // standard: [op, ["get", field], value]
    if (Array.isArray(e[1]) && e[1][0] === 'get') {
      return {
        id: crypto.randomUUID(),
        field: e[1][1] as string,
        operator: e[0] as string,
        value: String(e[2] ?? ''),
      };
    }

    return null;
  }

  // Handle "all" or "any" combinator expressions
  if (expr[0] === 'all' || expr[0] === 'any') {
    const combinator = expr[0] as 'all' | 'any';
    const results: FilterCondition[] = [];
    for (let i = 1; i < expr.length; i++) {
      if (!Array.isArray(expr[i])) {
        return { kind: 'opaque', raw: expr };
      }
      // Array.isArray confirms expr[i] is an array; cast narrows for parseSingle's signature.
      const parsed = parseSingle(expr[i] as unknown[]);
      if (parsed === null) {
        // Any unparseable sub-expression makes the whole thing opaque
        return { kind: 'opaque', raw: expr };
      }
      results.push(parsed);
    }
    return { kind: 'editable', combinator, conditions: results };
  }

  // Bare single expression
  const single = parseSingle(expr);
  if (single) {
    return { kind: 'editable', combinator: 'all', conditions: [single] };
  }

  // Unknown top-level expression — opaque
  return { kind: 'opaque', raw: expr };
}

export function LayerFilterEditor({
  columnInfo,
  filter,
  onFilterChange,
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

  // B-028: cleanup debounce timer on unmount
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

  // B-028: debounced version for value input keystrokes
  const debouncedEmit = useCallback(
    (updated: FilterCondition[], combo: 'all' | 'any') => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
      setConditions(updated);
      debounceTimerRef.current = setTimeout(() => {
        const newFilter = buildFilterExpression(updated, columnInfo, combo);
        lastEmittedFilterRef.current = newFilter;
        onFilterChange(newFilter);
      }, 180);
    },
    [columnInfo, onFilterChange],
  );

  function addCondition() {
    const newCond: FilterCondition = {
      id: crypto.randomUUID(),
      field: columnInfo[0]?.name ?? '',
      operator: OPERATORS_BY_TYPE[getFieldType(columnInfo[0]?.name ?? '')][0]?.value ?? '==',
      value: '',
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
        merged.value = '';
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
    try {
      const parsed = JSON.parse(rawText) as FilterSpecification;
      if (parsed !== null && !Array.isArray(parsed)) {
        setRawError(t('filters.rawJsonError'));
        return;
      }
      lastEmittedFilterRef.current = parsed;
      onFilterChange(parsed);
      const result = parseFilterExpression(parsed);
      applyParseResult(result);
      setRawError(null);
    } catch {
      setRawError(t('filters.rawJsonError'));
    }
  }

  function handleEnableRawMode() {
    setRawMode(true);
    setRawText(filter ? JSON.stringify(filter, null, 2) : '');
    setRawError(null);
  }

  return (
    <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
      {/* Header row: title + raw toggle */}
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium">{t('filters.title')}</div>
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
              <div key={cond.id} className="flex items-center gap-1.5">
                {/* Field select */}
                <Select
                  value={cond.field}
                  onValueChange={(val) => updateCondition(cond.id, { field: val })}
                  aria-label={t('filters.field')}
                >
                  <SelectTrigger className="h-7 text-xs flex-1 min-w-0">
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

                {/* Operator select */}
                <Select
                  value={cond.operator}
                  onValueChange={(val) => updateCondition(cond.id, { operator: val })}
                  aria-label={t('filters.op')}
                >
                  <SelectTrigger className="h-7 text-xs w-24 shrink-0">
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
                {cond.operator !== 'is_null' && cond.operator !== 'has' && (
                  getFieldType(cond.field) === 'boolean' && cond.operator === '==' ? (
                    <Select
                      value={cond.value || 'true'}
                      onValueChange={(val) => updateCondition(cond.id, { value: val })}
                    >
                      <SelectTrigger className="h-7 text-xs w-24 shrink-0" aria-label={t('filters.value')}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true" className="text-xs">true</SelectItem>
                        <SelectItem value="false" className="text-xs">false</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      className="h-7 text-xs flex-1 min-w-0"
                      placeholder={t('filters.value')}
                      aria-label={t('filters.value')}
                      value={cond.value}
                      onChange={(e) => updateCondition(cond.id, { value: e.target.value }, true)}
                    />
                  )
                )}

                {/* Remove button */}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => removeCondition(cond.id)}
                  aria-label={t('filters.removeCondition', { defaultValue: 'Remove condition' })}
                >
                  <X className="h-3 w-3" />
                </Button>
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

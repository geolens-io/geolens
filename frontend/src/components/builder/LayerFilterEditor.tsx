import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X } from 'lucide-react';
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
  ],
  number: [
    { label: '=', value: '==' },
    { label: '!=', value: '!=' },
    { label: '>', value: '>' },
    { label: '<', value: '<' },
    { label: '>=', value: '>=' },
    { label: '<=', value: '<=' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
  ],
  boolean: [
    { labelKey: 'filters.operators.equals', value: '==' },
    { labelKey: 'filters.operators.isNull', value: 'is_null' },
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
): FilterSpecification | null {
  const valid = conditions.filter((c) => c.field && c.operator);
  if (valid.length === 0) return null;

  const expressions: unknown[] = [];

  for (const cond of valid) {
    const col = columnInfo.find((c) => c.name === cond.field);
    const pgType = col?.type ?? 'text';

    if (cond.operator === 'is_null') {
      expressions.push(['!', ['has', cond.field]]);
    } else if (cond.operator === 'contains') {
      expressions.push(['in', cond.value, ['get', cond.field]]);
    } else {
      const coerced = coerceValue(cond.value, pgType);
      expressions.push([cond.operator, ['get', cond.field], coerced]);
    }
  }

  if (expressions.length === 1) return expressions[0] as FilterSpecification;
  return ['all', ...expressions] as FilterSpecification;
}

export function parseFilterExpression(expr: FilterSpecification | null): FilterCondition[] {
  if (!expr || !Array.isArray(expr) || expr.length === 0) return [];

  function parseSingle(e: unknown[]): FilterCondition | null {
    if (!Array.isArray(e) || e.length === 0) return null;

    // is_null: ["!", ["has", field]]
    if (e[0] === '!' && Array.isArray(e[1]) && e[1][0] === 'has') {
      return {
        id: crypto.randomUUID(),
        field: e[1][1] as string,
        operator: 'is_null',
        value: '',
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

  if (expr[0] === 'all') {
    const results: FilterCondition[] = [];
    for (let i = 1; i < expr.length; i++) {
      const parsed = parseSingle(expr[i] as unknown[]);
      if (parsed) results.push(parsed);
    }
    return results;
  }

  const single = parseSingle(expr);
  return single ? [single] : [];
}

export function LayerFilterEditor({
  columnInfo,
  filter,
  onFilterChange,
}: LayerFilterEditorProps) {
  const { t } = useTranslation('builder');
  const initializedRef = useRef(false);
  const [conditions, setConditions] = useState<FilterCondition[]>([]);

  // Sync from filter prop on initial mount only
  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      setConditions(parseFilterExpression(filter));
    }
  }, [filter]);

  function getFieldType(fieldName: string): ColumnType {
    const col = columnInfo.find((c) => c.name === fieldName);
    return col ? classifyColumnType(col.type) : 'other';
  }

  function emitChange(updated: FilterCondition[]) {
    setConditions(updated);
    onFilterChange(buildFilterExpression(updated, columnInfo));
  }

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

  function updateCondition(id: string, patch: Partial<FilterCondition>) {
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
    emitChange(updated);
  }

  return (
    <div className="space-y-3 p-3 bg-muted/30 rounded-md border">
      <div className="text-xs font-medium">{t('filters.title')}</div>

      {conditions.map((cond) => {
        const colType = getFieldType(cond.field);
        const ops = OPERATORS_BY_TYPE[colType];

        return (
          <div key={cond.id} className="flex items-center gap-1.5">
            {/* Field select */}
            <Select
              value={cond.field}
              onValueChange={(val) => updateCondition(cond.id, { field: val })}
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

            {/* Value input (hidden for is_null) */}
            {cond.operator !== 'is_null' && (
              <Input
                className="h-7 text-xs flex-1 min-w-0"
                placeholder={t('filters.value')}
                value={cond.value}
                onChange={(e) => updateCondition(cond.id, { value: e.target.value })}
              />
            )}

            {/* Remove button */}
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0"
              onClick={() => removeCondition(cond.id)}
              aria-label={t('filters.removeFilter')}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        );
      })}

      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={addCondition}>
        <Plus className="h-3 w-3 mr-1" />
        {t('filters.addFilter')}
      </Button>
    </div>
  );
}

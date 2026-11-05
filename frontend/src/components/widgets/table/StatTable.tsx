import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { WidgetRenderProps } from '../contract';
import { PICKED_GLYPH } from '../PickedMark';
import { selectedValues, togglePick } from '../selection';
import type { TableConfig } from './definition';
import { useTableText } from './table-rows';

/**
 * One row per group, one column per statistic. Where the host links widgets
 * (`onSelect`), a row's button picks its group, as a bar does; picking it
 * again clears the pick. A picked row is marked and keeps full weight.
 */
export function StatTable({ config, data, selection, onSelect, columnLabel }: WidgetRenderProps<TableConfig>) {
  const { t } = useTranslation('widgets');
  const text = useTableText(config, data, columnLabel);
  const { rows } = text;
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(rows ? 'noRows' : 'noData')}</p>;
  }
  const picked = selectedValues(selection, config.group_column);
  return (
    <div className="space-y-1">
      <table className="w-full text-sm">
        <caption className="sr-only">{text.summary}</caption>
        <thead>
          <tr className="border-b text-left">
            <th scope="col" className="py-1 pr-2 font-medium">
              {text.groupHeader}
            </th>
            {text.statHeaders.map((header, index) => (
              <th key={index} scope="col" className="py-1 pl-2 text-right font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const isPicked = picked.includes(row.key);
            const pick = () =>
              onSelect?.(
                togglePick(isPicked && picked.length === 1, {
                  column: config.group_column,
                  label: row.label,
                  values: [row.key],
                }),
              );
            return (
              <tr
                key={index}
                aria-selected={onSelect ? isPicked : undefined}
                data-picked={isPicked || undefined}
                className={cn(
                  'border-b last:border-0',
                  onSelect && 'cursor-pointer hover:bg-muted/50',
                  isPicked && 'bg-muted font-semibold',
                  onSelect && picked.length > 0 && !isPicked && 'opacity-75',
                )}
                onClick={onSelect ? pick : undefined}
              >
                <th scope="row" className="py-1 pr-2 text-left font-normal break-words">
                  {onSelect ? (
                    <button
                      type="button"
                      aria-pressed={isPicked}
                      className="rounded-sm text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                    >
                      {row.label}
                    </button>
                  ) : (
                    row.label
                  )}
                  {isPicked && (
                    <span aria-hidden="true" className="ms-1 font-semibold">
                      {PICKED_GLYPH}
                    </span>
                  )}
                </th>
                {row.texts.map((value, statIndex) => (
                  <td key={statIndex} className="py-1 pl-2 text-right tabular-nums">
                    {value}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {text.truncated && (
        <p className="text-xs text-muted-foreground">{t('types.table.truncated', { count: rows.length })}</p>
      )}
    </div>
  );
}

import { useTranslation } from 'react-i18next';
import type { WidgetRenderProps } from '../contract';
import type { FeatureListConfig } from './definition';
import { useFeatureRows, type FeatureRow } from './feature-list-rows';

/** A feature's title with its subtitle under it; `coded` adds the stored value after a label. */
export function FeatureText({ row, coded }: { row: FeatureRow; coded?: boolean }) {
  return (
    <>
      <span className="block text-sm break-words">{coded ? row.listTitle : row.title}</span>
      {row.subtitle !== undefined && (
        <span className="block text-xs text-muted-foreground break-words">{coded ? row.listSubtitle : row.subtitle}</span>
      )}
    </>
  );
}

/** The listed features as plain text, with no zoom and no paging. */
export function FeatureListFallback({ config, data, valueLabel }: WidgetRenderProps<FeatureListConfig>) {
  const { t } = useTranslation('widgets');
  const { rows } = useFeatureRows(config, data, valueLabel);
  if (!rows) return <p className="text-sm text-muted-foreground">{t('noData')}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{t('noRows')}</p>;
  return (
    <ul className="divide-y rounded-md border">
      {rows.map((row) => (
        <li key={row.id} className="px-2 py-1.5">
          <FeatureText row={row} coded />
        </li>
      ))}
    </ul>
  );
}

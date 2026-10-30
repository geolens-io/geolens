import { useTranslation } from 'react-i18next';
import { PickedMark } from './PickedMark';

interface ValueTableRow {
  label: string;
  text: string;
  picked?: boolean;
}

/**
 * A widget's data as a two-column table, its text alternative. Without rows
 * yet it says there is no data; `other` adds a last row for values a top-N
 * list leaves out.
 */
export function ValueTable({
  caption,
  labelHeader,
  valueHeader,
  rows,
  other,
}: {
  caption: string;
  labelHeader: string;
  valueHeader: string;
  rows?: readonly ValueTableRow[];
  other?: string;
}) {
  const { t } = useTranslation('widgets');
  if (!rows || rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(rows ? 'noRows' : 'noData')}</p>;
  }
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b text-left">
          <th scope="col" className="py-1 pr-2 font-medium">
            {labelHeader}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {valueHeader}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index} className="border-b last:border-0">
            <th scope="row" className="py-1 pr-2 text-left font-normal break-words">
              {row.label}
              {row.picked && <PickedMark />}
            </th>
            <td className="py-1 text-right tabular-nums">{row.text}</td>
          </tr>
        ))}
        {other !== undefined && (
          <tr>
            <th scope="row" className="py-1 pr-2 text-left font-normal text-muted-foreground">
              {t('other')}
            </th>
            <td className="py-1 text-right tabular-nums text-muted-foreground">{other}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

import { Globe, Lock, ShieldAlert, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getVisibilityLabel } from '@/i18n/labels';

export function VisibilityIcon({
  visibility,
  withLabel = true,
}: {
  visibility: string;
  /** Include an sr-only text label. Default true (icon-only uses like the map
   *  cards need it). Pass false where the visibility is already rendered as
   *  adjacent VISIBLE text to avoid double-announcing ("Public Public"). #305 */
  withLabel?: boolean;
}) {
  const { t } = useTranslation();
  const Icon =
    visibility === 'public'
      ? Globe
      : visibility === 'internal'
        ? Users
        : visibility === 'restricted'
          ? ShieldAlert
          : Lock;
  const colorClass =
    visibility === 'public'
      ? 'text-success'
      : visibility === 'internal' || visibility === 'restricted'
        ? 'text-warning'
        : 'text-muted-foreground';
  return (
    <>
      <Icon className={`h-3.5 w-3.5 ${colorClass}`} aria-hidden="true" />
      {withLabel && <span className="sr-only">{getVisibilityLabel(t, visibility)}</span>}
    </>
  );
}

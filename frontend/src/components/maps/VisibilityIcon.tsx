import { Globe, Lock, ShieldAlert, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getVisibilityLabel } from '@/i18n/labels';

export function VisibilityIcon({ visibility }: { visibility: string }) {
  const { t } = useTranslation();
  // v1047 A11Y-COLOR-01: meaning was conveyed by icon/color alone. Render the
  // glyph as decorative (aria-hidden) and add an sr-only text label so the
  // visibility is announced to screen readers — and internal vs restricted,
  // which share the warning color, are differentiated by text. An sr-only span
  // (rather than role="img" on the icon) keeps the icon out of by-role image
  // queries used for dataset/map thumbnails.
  const label = getVisibilityLabel(t, visibility);
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
      <span className="sr-only">{label}</span>
    </>
  );
}

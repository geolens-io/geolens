import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { getVisibilityLabel } from '@/i18n/labels';
import { visibilityColors } from '@/lib/status-colors';
import { VisibilityIcon } from './VisibilityIcon';

/** A visibility shown as an icon and its label, so it doesn't rely on colour alone. */
export function VisibilityBadge({ visibility }: { visibility: string }) {
  const { t } = useTranslation();
  return (
    <Badge
      variant="outline"
      className={`shrink-0 gap-1 ${visibilityColors[visibility] ?? 'border-border bg-muted text-muted-foreground'}`}
    >
      <VisibilityIcon visibility={visibility} withLabel={false} />
      {getVisibilityLabel(t, visibility)}
    </Badge>
  );
}

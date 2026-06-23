import { Globe, Lock, ShieldAlert, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getVisibilityLabel } from '@/i18n/labels';

export function VisibilityIcon({ visibility }: { visibility: string }) {
  const { t } = useTranslation();
  // v1047 A11Y-COLOR-01: meaning was conveyed by icon/color alone; give each
  // icon an accessible name so screen readers announce the visibility (and
  // internal vs restricted are differentiated by text, not just shared color).
  const label = getVisibilityLabel(t, visibility);
  if (visibility === 'public')
    return <Globe className="h-3.5 w-3.5 text-success" role="img" aria-label={label} />;
  if (visibility === 'internal')
    return <Users className="h-3.5 w-3.5 text-warning" role="img" aria-label={label} />;
  if (visibility === 'restricted')
    return <ShieldAlert className="h-3.5 w-3.5 text-warning" role="img" aria-label={label} />;
  return <Lock className="h-3.5 w-3.5 text-muted-foreground" role="img" aria-label={label} />;
}

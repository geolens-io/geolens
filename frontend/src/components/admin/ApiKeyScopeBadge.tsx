import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';

// Literal keys, so the unused-key checks see each one.
const SCOPE_LABEL_KEYS: Record<string, string> = {
  read_only: 'admin:apiKeys.scopeReadOnly',
  dataset_write: 'admin:apiKeys.scopeDatasetWrite',
  dataset_append: 'admin:apiKeys.scopeDatasetAppend',
};

/** Names a key's scope in a key list; a full-access key gets no badge. */
export function ApiKeyScopeBadge({ scope }: { scope: string }) {
  const { t } = useTranslation();
  const labelKey = SCOPE_LABEL_KEYS[scope];
  if (!labelKey) return null;
  return (
    <Badge variant="secondary" className="px-1.5">
      {t(labelKey)}
    </Badge>
  );
}

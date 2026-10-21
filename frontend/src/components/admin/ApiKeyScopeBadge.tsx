import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import type { ApiKeyScope, DatasetApiKeyCreateRequest } from '@/types/api';

type LimitedScope = Exclude<
  NonNullable<ApiKeyScope | DatasetApiKeyCreateRequest['scope']>,
  'full'
>;

// Keyed by every scope a key can be minted with, so a new one fails typecheck
// until it has a label. Literal keys, so the unused-key checks see each one.
const SCOPE_LABEL_KEYS: Record<LimitedScope, string> = {
  read_only: 'admin:apiKeys.scopeReadOnly',
  publish: 'admin:apiKeys.scopePublish',
  dataset_write: 'admin:apiKeys.scopeDatasetWrite',
  dataset_append: 'admin:apiKeys.scopeDatasetAppend',
};

/** Names a key's scope in a key list; a full-access key gets no badge. */
export function ApiKeyScopeBadge({ scope }: { scope: string }) {
  const { t } = useTranslation();
  if (scope === 'full') return null;
  const labelKey = SCOPE_LABEL_KEYS[scope as LimitedScope];
  // A scope this build doesn't know is still not a full key, so name it as is.
  return (
    <Badge variant="secondary" className="px-1.5">
      {labelKey ? t(labelKey) : scope}
    </Badge>
  );
}

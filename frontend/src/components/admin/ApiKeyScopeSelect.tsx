import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ApiKeyScope } from '@/types/api';

interface ApiKeyScopeSelectProps {
  value: ApiKeyScope;
  onChange: (value: ApiKeyScope) => void;
  disabled?: boolean;
}

/**
 * Scope picker for a new API key (#875).
 *
 * Shared by the self-service and admin mint forms so the two surfaces cannot
 * drift: an admin minting a service-account key is the most likely caller to
 * want `read_only`, and it would be odd for that surface to offer a different
 * set of choices than a user minting their own.
 */
export function ApiKeyScopeSelect({ value, onChange, disabled }: ApiKeyScopeSelectProps) {
  const { t } = useTranslation('admin');
  const labelId = useId();

  return (
    <div className="flex items-center gap-2">
      <span id={labelId} className="text-xs text-muted-foreground">
        {t('apiKeys.scope')}
      </span>
      <Select
        value={value}
        onValueChange={(v) => onChange(v as ApiKeyScope)}
        disabled={disabled}
      >
        <SelectTrigger className="h-8 w-auto min-w-[130px] text-sm" aria-labelledby={labelId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="full">{t('apiKeys.scopeFull')}</SelectItem>
          <SelectItem value="read_only">{t('apiKeys.scopeReadOnly')}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

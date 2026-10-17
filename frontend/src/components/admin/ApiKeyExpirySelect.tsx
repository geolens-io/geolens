import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { API_KEY_EXPIRY_PRESETS, type ApiKeyExpiryPreset } from '@/lib/api-key-expiry';

interface ApiKeyExpirySelectProps {
  value: ApiKeyExpiryPreset;
  onChange: (value: ApiKeyExpiryPreset) => void;
  disabled?: boolean;
}

/** Expiry picker for a new API key, shared by the self-service and admin mint forms. */
export function ApiKeyExpirySelect({ value, onChange, disabled }: ApiKeyExpirySelectProps) {
  const { t } = useTranslation('admin');
  const labelId = useId();

  return (
    <div className="flex items-center gap-2">
      <span id={labelId} className="text-xs text-muted-foreground">
        {t('apiKeys.expiry')}
      </span>
      <Select
        value={value}
        onValueChange={(v) => onChange(v as ApiKeyExpiryPreset)}
        disabled={disabled}
      >
        <SelectTrigger className="h-8 w-auto min-w-[130px] text-sm" aria-labelledby={labelId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {API_KEY_EXPIRY_PRESETS.map((preset) => (
            <SelectItem key={preset} value={preset}>
              {t(`apiKeys.expiryOptions.${preset}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

import { useTranslation } from 'react-i18next';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface RoleSelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

// fix(#438): DS-08 — was a native <select>, which skips the 44px coarse-pointer
// target treatment and the app's themed dropdown. Routed through ui/select.
export function RoleSelect({ id, value, onChange, disabled }: RoleSelectProps) {
  const { t } = useTranslation('admin');

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="viewer">{t('roles.viewer')}</SelectItem>
        <SelectItem value="editor">{t('roles.editor')}</SelectItem>
        <SelectItem value="admin">{t('roles.admin')}</SelectItem>
      </SelectContent>
    </Select>
  );
}

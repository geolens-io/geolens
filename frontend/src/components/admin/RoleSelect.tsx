import { useTranslation } from 'react-i18next';

interface RoleSelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function RoleSelect({ id, value, onChange, disabled }: RoleSelectProps) {
  const { t } = useTranslation('admin');

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-xs focus:outline-none focus:ring-2 focus:ring-ring/50"
    >
      <option value="viewer">{t('roles.viewer')}</option>
      <option value="editor">{t('roles.editor')}</option>
      <option value="admin">{t('roles.admin')}</option>
    </select>
  );
}

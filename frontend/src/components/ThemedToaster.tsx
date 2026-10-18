import { Toaster } from 'sonner';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/components/theme-provider';

export function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  const { t } = useTranslation('common');
  // richColors tells success/error/warning/info apart by hue; closeButton makes
  // every toast dismissable. Sonner appends the hotkey to the label.
  return (
    <Toaster
      theme={resolvedTheme}
      richColors
      closeButton
      containerAriaLabel={t('notificationsRegion')}
    />
  );
}

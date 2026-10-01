import { Toaster } from 'sonner';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/components/theme-provider';

export function ThemedToaster() {
  const { resolvedTheme } = useTheme();
  const { t } = useTranslation('common');
  // #305: richColors differentiates success/error/warning/info by
  // hue (was a single neutral surface for all 183 call sites); closeButton
  // makes every toast dismissable. Sonner appends the hotkey to the label.
  return (
    <Toaster
      theme={resolvedTheme}
      richColors
      closeButton
      containerAriaLabel={t('notificationsRegion')}
    />
  );
}

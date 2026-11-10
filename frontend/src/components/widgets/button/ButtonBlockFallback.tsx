import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { isSafeHttpUrl } from '@/lib/safe-http-url';
import type { WidgetRenderProps } from '../contract';
import type { ButtonConfig } from './definition';

/**
 * A link styled as a button. An address that isn't http or https is never
 * linked: the label shows as plain text.
 */
export function ButtonBlockFallback({ config }: WidgetRenderProps<ButtonConfig>) {
  const { t } = useTranslation('widgets');
  if (!isSafeHttpUrl(config.url)) return <p className="text-sm break-words">{config.label}</p>;
  return (
    <div>
      <Button asChild>
        <a
          href={config.url}
          {...(config.new_tab ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
        >
          {config.label}
          {config.new_tab && (
            <>
              {' '}
              <span className="sr-only">{t('types.button.opensInNewTab')}</span>
            </>
          )}
        </a>
      </Button>
    </div>
  );
}

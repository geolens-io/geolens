import * as React from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * Password field with a built-in reveal toggle.
 *
 * Extracted from the login form so every password entry point (login, register,
 * admin user create, settings provider secrets) shares one accessible, branded
 * reveal control instead of hand-rolling `type={show ? 'text' : 'password'}`.
 * The eye button carries the same focus-visible ring as the other primitives and
 * a translated aria-label (with an English default so it stays labelled even on
 * surfaces that have not loaded the `auth` namespace).
 *
 * `type` is owned by the toggle and intentionally not forwarded.
 */
export type PasswordInputProps = Omit<React.ComponentProps<typeof Input>, 'type'>;

export const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, ...props }, ref) => {
    const [show, setShow] = React.useState(false);
    const { t } = useTranslation('auth');

    return (
      <div className="relative">
        <Input
          ref={ref}
          type={show ? 'text' : 'password'}
          className={cn('pe-11', className)}
          {...props}
        />
        <button
          type="button"
          onClick={() => setShow((visible) => !visible)}
          className="absolute inset-y-0 end-1 my-auto flex size-8 items-center justify-center rounded-md text-muted-foreground transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
          aria-label={show
            ? t('hidePassword', { defaultValue: 'Hide password' })
            : t('showPassword', { defaultValue: 'Show password' })}
        >
          {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
    );
  },
);

PasswordInput.displayName = 'PasswordInput';

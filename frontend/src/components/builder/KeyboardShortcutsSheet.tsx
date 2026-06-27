import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
// builder-audit #338 STACK-07: shared platform detection + Save chord (was duplicated
// from MapTitleBar.tsx).
import { SAVE_SHORTCUT } from '@/lib/platform';

interface ShortcutRowProps {
  id: string;
  label: string;
  chord: string;
}

function ShortcutRow({ id, label, chord }: ShortcutRowProps) {
  return (
    <div
      data-testid={`shortcut-${id}`}
      className="flex items-center justify-between gap-4 rounded px-1 py-1.5 text-sm hover:bg-muted/40"
    >
      <span className="text-foreground">{label}</span>
      <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
        {chord}
      </kbd>
    </div>
  );
}

interface KeyboardShortcutsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function KeyboardShortcutsSheet({
  open,
  onOpenChange,
}: KeyboardShortcutsSheetProps) {
  const { t } = useTranslation('builder');

  const shortcuts: ShortcutRowProps[] = [
    {
      id: 'save',
      label: t('a11y.shortcuts.save', { defaultValue: 'Save map' }),
      chord: SAVE_SHORTCUT,
    },
    {
      id: 'pan',
      label: t('a11y.shortcuts.pan', { defaultValue: 'Pan tool' }),
      chord: 'V',
    },
    {
      id: 'measure',
      label: t('a11y.shortcuts.measure', { defaultValue: 'Measure tool' }),
      chord: 'M',
    },
    {
      id: 'legend',
      label: t('a11y.shortcuts.legend', { defaultValue: 'Toggle legend' }),
      chord: 'L',
    },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {t('a11y.shortcuts.title', { defaultValue: 'Keyboard shortcuts' })}
          </DialogTitle>
          <DialogDescription>
            {t('a11y.shortcuts.description', {
              defaultValue: 'Speed up map authoring with these shortcuts.',
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="mt-2 flex flex-col gap-0.5">
          {shortcuts.map((s) => (
            <ShortcutRow key={s.id} {...s} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

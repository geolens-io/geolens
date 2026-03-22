import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { Pencil } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { DatasetEditCapability } from '@/hooks/use-dataset-edit-capabilities';
import { RoleCapabilityHint } from '@/components/dataset/RoleCapabilityHint';

interface EditableFieldShellProps {
  capability: DatasetEditCapability;
  children: ReactNode;
  className?: string;
  testId?: string;
  onAttemptEdit?: () => void;
}

export function EditableFieldShell({
  capability,
  children,
  className,
  testId,
  onAttemptEdit,
}: EditableFieldShellProps) {
  const [showDeniedHint, setShowDeniedHint] = useState(false);
  const isInteractive = Boolean(onAttemptEdit) || (!capability.editable && capability.canAttempt);
  const supportsHintOnAttempt = capability.reason === 'insufficient_role';

  const handleAttempt = useCallback(() => {
    if (capability.editable) {
      setShowDeniedHint(false);
      onAttemptEdit?.();
      return;
    }

    if (capability.canAttempt && supportsHintOnAttempt) {
      setShowDeniedHint(true);
    }
  }, [capability, onAttemptEdit, supportsHintOnAttempt]);

  return (
    <div className={cn('space-y-2', className)}>
      <div
        role={isInteractive ? 'button' : undefined}
        tabIndex={isInteractive ? 0 : undefined}
        onClick={isInteractive ? handleAttempt : undefined}
        onKeyDown={isInteractive ? (event) => {
          if (event.target !== event.currentTarget) {
            return;
          }
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleAttempt();
          }
        } : undefined}
        className={cn(
          'group w-full rounded-md px-2 py-1.5 transition-colors',
          capability.editable
            ? 'cursor-pointer border border-primary/20 bg-primary/5 hover:bg-primary/10'
            : 'border border-transparent bg-transparent',
          !capability.editable && capability.canAttempt && 'cursor-help',
        )}
        data-editable={capability.editable ? 'true' : 'false'}
        data-can-attempt={capability.canAttempt ? 'true' : 'false'}
        data-testid={testId ?? 'editable-field-shell'}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">{children}</div>
          {capability.editable && (
            <Pencil
              className="mt-0.5 h-3 w-3 shrink-0 text-primary/70"
              aria-hidden
              data-testid="editable-field-shell-icon"
            />
          )}
        </div>
      </div>

      {showDeniedHint && supportsHintOnAttempt && (
        <RoleCapabilityHint
          reason={capability.reason}
          helper={capability.helper}
        />
      )}
    </div>
  );
}

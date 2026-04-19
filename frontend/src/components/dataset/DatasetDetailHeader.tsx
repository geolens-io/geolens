import { Fragment } from 'react';
import type { ComponentProps, ComponentType } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal } from 'lucide-react';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { Button } from '@/components/ui/button';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useIsMobile } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';

type ActionVariant = Exclude<ComponentProps<typeof Button>['variant'], null | undefined>;

export interface DatasetDetailHeaderAction {
  id: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  onSelect: () => void;
  priority: number;
  visible: boolean;
  disabled?: boolean;
  variant?: ActionVariant;
}

export interface DatasetDetailHeaderBreadcrumb {
  label: string;
  to: string;
}

interface DatasetDetailHeaderProps {
  title: string;
  onTitleSave?: (newTitle: string) => Promise<void>;
  canEditTitle?: boolean;
  actions?: DatasetDetailHeaderAction[];
  breadcrumbs?: DatasetDetailHeaderBreadcrumb[];
  leadingContent?: React.ReactNode;
  statsLine?: React.ReactNode;
  className?: string;
}

export const DESKTOP_PRIMARY_ACTION_LIMIT = 1;
export const MOBILE_PRIMARY_ACTION_LIMIT = 0;

export function partitionActions(actions: DatasetDetailHeaderAction[], isMobile: boolean) {
  const visibleActions = actions
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => action.visible)
    .sort((a, b) => {
      if (a.action.priority !== b.action.priority) {
        return a.action.priority - b.action.priority;
      }
      return a.index - b.index;
    })
    .map(({ action }) => action);

  const primaryLimit = isMobile ? MOBILE_PRIMARY_ACTION_LIMIT : DESKTOP_PRIMARY_ACTION_LIMIT;
  return {
    primary: visibleActions.slice(0, primaryLimit),
    overflow: visibleActions.slice(primaryLimit),
  };
}

export function DatasetDetailHeader({
  title,
  onTitleSave,
  canEditTitle = false,
  actions = [],
  breadcrumbs,
  leadingContent,
  statsLine,
  className,
}: DatasetDetailHeaderProps) {
  const { t } = useTranslation('dataset');
  const isMobile = useIsMobile();
  const { primary, overflow } = partitionActions(actions, isMobile);
  const isTitleEditable = canEditTitle && Boolean(onTitleSave);

  return (
    <div className={cn('space-y-3', className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <Breadcrumb>
          <BreadcrumbList>
            {breadcrumbs.map((crumb, index) => (
              <Fragment key={crumb.to}>
                {index > 0 && <BreadcrumbSeparator />}
                <BreadcrumbItem>
                  <BreadcrumbLink asChild>
                    <Link to={crumb.to}>{crumb.label}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
              </Fragment>
            ))}
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>{title}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
      )}

      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-2 md:gap-4">
        <div className="min-w-0">
          <h1 className="text-3xl md:text-4xl font-medium tracking-tight break-words">
            {isTitleEditable ? (
              <InlineEdit
                value={title}
                onSave={onTitleSave!}
                as="span"
                canEdit
                className="inline"
              />
            ) : (
              title
            )}
          </h1>
          {statsLine && (
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground flex-wrap">
              {statsLine}
            </div>
          )}
        </div>

        {(leadingContent || primary.length > 0 || overflow.length > 0) && (
          <div className="flex items-center gap-2 flex-wrap">
            {leadingContent}
            {primary.map((action) => (
              <Button
                key={action.id}
                variant={action.variant ?? 'outline'}
                size="sm"
                onClick={action.onSelect}
                disabled={action.disabled}
                data-testid={`dataset-header-action-${action.id}`}
              >
                <action.icon className="h-4 w-4" />
                {action.label}
              </Button>
            ))}

            {overflow.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    aria-label={t('header.moreActions', { defaultValue: 'More actions' })}
                    data-testid="dataset-header-overflow-trigger"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {overflow.map((action) => (
                    <DropdownMenuItem
                      key={action.id}
                      disabled={action.disabled}
                      onSelect={action.onSelect}
                      data-testid={`dataset-header-overflow-${action.id}`}
                    >
                      <action.icon className="h-4 w-4" />
                      {action.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

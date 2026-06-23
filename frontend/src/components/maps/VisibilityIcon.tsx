import { Globe, Lock, ShieldAlert, Users } from 'lucide-react';

export function VisibilityIcon({ visibility }: { visibility: string }) {
  // #305: purely decorative (aria-hidden). Every call site renders the
  // visibility label as visible text right next to this icon (MapCard,
  // AccessTab, BuilderDialogs, …), so an sr-only label here only
  // double-announces ("Public Public") — the adjacent text already conveys it.
  const Icon =
    visibility === 'public'
      ? Globe
      : visibility === 'internal'
        ? Users
        : visibility === 'restricted'
          ? ShieldAlert
          : Lock;
  const colorClass =
    visibility === 'public'
      ? 'text-success'
      : visibility === 'internal' || visibility === 'restricted'
        ? 'text-warning'
        : 'text-muted-foreground';
  return <Icon className={`h-3.5 w-3.5 ${colorClass}`} aria-hidden="true" />;
}

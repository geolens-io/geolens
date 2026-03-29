import { Globe, Lock, Users } from 'lucide-react';

export function VisibilityIcon({ visibility }: { visibility: string }) {
  if (visibility === 'public') return <Globe className="h-3.5 w-3.5 text-success" />;
  if (visibility === 'internal') return <Users className="h-3.5 w-3.5 text-amber-500" />;
  return <Lock className="h-3.5 w-3.5 text-muted-foreground" />;
}

import type { WidgetContext } from '../types';

export function PlaceholderWidget({ ctx }: { ctx: WidgetContext }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">Widget system active</p>
      <p className="text-xs">
        <span className="font-medium">{ctx.layers.length}</span>{' '}
        <span className="text-muted-foreground">layer{ctx.layers.length !== 1 ? 's' : ''}</span>
      </p>
      <p className="text-xs text-muted-foreground font-mono truncate max-w-40" title={ctx.mapId}>
        {ctx.mapId}
      </p>
    </div>
  );
}

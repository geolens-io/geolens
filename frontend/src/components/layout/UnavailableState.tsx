import type { ElementType, ReactNode } from 'react';

interface UnavailableStateProps {
  icon: ElementType;
  title: string;
  /** One or more paragraphs under the title. */
  body: ReactNode;
  /** The ways out, usually a primary and an outline button. */
  actions: ReactNode;
}

/** A full-page notice for something that failed to load or can't be opened, with ways out. */
export function UnavailableState({ icon: Icon, title, body, actions }: UnavailableStateProps) {
  return (
    <div className="app-surface-gradient flex min-h-0 flex-1 overflow-y-auto px-6">
      <div className="m-auto flex w-full max-w-xl flex-col items-center rounded-2xl border bg-background/95 p-8 text-center shadow-lg backdrop-blur">
        <Icon className="size-10 text-muted-foreground" aria-hidden="true" />
        <div className="mt-4 space-y-2 text-center">
          <h1 className="text-2xl font-semibold text-foreground">{title}</h1>
          {body}
        </div>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">{actions}</div>
      </div>
    </div>
  );
}

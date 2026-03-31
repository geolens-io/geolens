/** Floating title pill shown over public/shared map viewers. */
export function MapTitlePill({ name }: { name: string }) {
  return (
    <div className="absolute top-3 left-14 z-10 pointer-events-none">
      <div className="bg-background/80 backdrop-blur-sm rounded-full px-3 py-1 shadow-sm border border-border/50">
        <h1
          className="text-sm font-medium text-foreground truncate max-w-[200px]"
          title={name}
        >
          {name}
        </h1>
      </div>
    </div>
  );
}

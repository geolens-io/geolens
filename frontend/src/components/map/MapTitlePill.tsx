import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Info, X } from 'lucide-react';

interface MapTitlePillProps {
  name: string;
  description?: string | null;
}

/** Floating title pill shown over public/shared map viewers. */
export function MapTitlePill({ name, description }: MapTitlePillProps) {
  const { t } = useTranslation('common');
  const [showDesc, setShowDesc] = useState(false);
  const hasDescription = !!description?.trim();

  return (
    <div className="absolute top-3 left-14 z-20 max-w-[320px] sm:max-w-[400px]">
      <div className="bg-background/80 backdrop-blur-sm rounded-lg px-3 py-1.5 shadow-sm border border-border/50">
        <div className="flex items-center gap-1.5">
          <h1
            className="text-sm font-medium text-foreground truncate"
            title={name}
          >
            {name}
          </h1>
          {hasDescription && (
            <button
              type="button"
              onClick={() => setShowDesc((prev) => !prev)}
              aria-expanded={showDesc}
              aria-label={showDesc
                ? t('viewer.hideDescription')
                : t('viewer.showDescription')}
              className="flex-shrink-0 p-0.5 rounded hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
            >
              {showDesc
                ? <X className="w-3.5 h-3.5" aria-hidden="true" />
                : <Info className="w-3.5 h-3.5" aria-hidden="true" />}
            </button>
          )}
        </div>
        {showDesc && hasDescription && (
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            {description}
          </p>
        )}
      </div>
    </div>
  );
}

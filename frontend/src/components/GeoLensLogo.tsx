import { cn } from '@/lib/utils';
import { useId } from 'react';

interface GeoLensLogoProps {
  variant?: 'full' | 'icon';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizes = {
  sm: { icon: 'h-5 w-5', text: 'text-base', gap: 'gap-1.5' },
  md: { icon: 'h-6 w-6', text: 'text-lg', gap: 'gap-1.5' },
  lg: { icon: 'h-8 w-8', text: 'text-2xl', gap: 'gap-2' },
};

function ReticleIcon({ className }: { className?: string }) {
  const clipId = useId();

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <clipPath id={clipId}>
          <circle cx="26" cy="26" r="18" />
        </clipPath>
      </defs>

      {/* Lens ring */}
      <circle cx="26" cy="26" r="18" fill="none" stroke="currentColor" strokeWidth="3.2" />

      {/* Graticule detail (clipped to lens) */}
      <g clipPath={`url(#${clipId})`} stroke="currentColor" fill="none" strokeWidth="1.6" opacity="0.5">
        <line x1="8" y1="26" x2="44" y2="26" />
        <line x1="26" y1="8" x2="26" y2="44" />
        <ellipse cx="26" cy="26" rx="9" ry="18" />
        <ellipse cx="26" cy="26" rx="18" ry="9" />
      </g>

      {/* Crosshair ticks */}
      <g stroke="currentColor" strokeWidth="2.8">
        <line x1="26" y1="3" x2="26" y2="6" />
        <line x1="26" y1="46" x2="26" y2="49" />
        <line x1="3" y1="26" x2="6" y2="26" />
        <line x1="46" y1="26" x2="49" y2="26" />
      </g>

      {/* Center dot */}
      <circle cx="26" cy="26" r="2" fill="currentColor" />

      {/* Magnifier handle */}
      <line x1="39" y1="39" x2="56" y2="56" stroke="currentColor" strokeWidth="4.8" strokeLinecap="round" />
    </svg>
  );
}

export function GeoLensLogo({
  variant = 'full',
  size = 'md',
  className,
}: GeoLensLogoProps) {
  const s = sizes[size];

  return (
    <span className={cn('inline-flex items-center', s.gap, className)}>
      <ReticleIcon className={cn(s.icon, 'shrink-0')} />
      {variant === 'full' && (
        <span className={cn(s.text, 'font-bold tracking-tight')}>
          Geo<span className="font-light text-muted-foreground">Lens</span>
        </span>
      )}
    </span>
  );
}
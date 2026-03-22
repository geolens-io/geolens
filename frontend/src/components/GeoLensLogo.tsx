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

function GlobeIcon({ className }: { className?: string }) {
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
          <circle cx="27" cy="27" r="22" />
        </clipPath>
      </defs>

      {/* Lens / globe ring */}
      <circle
        cx="27"
        cy="27"
        r="22"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
      />

      {/* Simplified globe detail */}
      <g
        clipPath={`url(#${clipId})`}
        stroke="currentColor"
        fill="none"
        strokeWidth="2"
        opacity="0.55"
      >
        <line x1="7" y1="27" x2="47" y2="27" />
        <ellipse cx="27" cy="27" rx="11" ry="22" />
      </g>

      {/* Handle */}
      <line
        x1="41"
        y1="41"
        x2="55"
        y2="55"
        stroke="currentColor"
        strokeWidth="4.5"
        strokeLinecap="round"
      />
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
      <GlobeIcon className={cn(s.icon, 'shrink-0')} />
      {variant === 'full' && (
        <span className={cn(s.text, 'font-semibold tracking-tight')}>
          Geo<span className="font-normal">Lens</span>
        </span>
      )}
    </span>
  );
}
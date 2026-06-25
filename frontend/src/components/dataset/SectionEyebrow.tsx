import type { ReactNode } from 'react';
import { CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

/**
 * Canonical "eyebrow" treatment for sidebar/section card titles on the dataset
 * detail page — the single source of truth for the mono-caps section marker.
 *
 * This is the strong tier of the page's two-tier label system: mono-caps section
 * *markers* (this style) vs. quiet sans field *labels* (see SideKV). Keeping it
 * in one place means the tier can evolve — or gain heading semantics — without
 * hunting down a copy-pasted class string across every card.
 */
export const SECTION_EYEBROW =
  'text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70';

interface SectionEyebrowProps {
  children: ReactNode;
  className?: string;
}

/** Convenience wrapper rendering a CardTitle with the eyebrow treatment. */
export function SectionEyebrow({ children, className }: SectionEyebrowProps) {
  return <CardTitle className={cn(SECTION_EYEBROW, className)}>{children}</CardTitle>;
}

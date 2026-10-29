import { useRef, type ReactNode } from 'react';
import { useAssetImage } from '@/hooks/use-asset-image';
import { useNearViewport } from '@/hooks/use-near-viewport';
import { cn } from '@/lib/utils';

interface AssetImageProps {
  /** The API path of the image; without one, `fallback` shows. */
  path: string | null;
  alt: string;
  className: string;
  /** Sizes the pulsing placeholder that holds the image's place while it loads. */
  placeholderClassName: string;
  /** Shown when there's no image, or it can't be loaded. */
  fallback: ReactNode;
  /** Wait to fetch until the placeholder nears the viewport. */
  lazy?: boolean;
  /** Names the placeholder for assistive technology; without it, it's hidden. */
  loadingLabel?: string;
}

/** An image fetched from the API with the reader's credentials. */
export function AssetImage({
  path,
  alt,
  className,
  placeholderClassName,
  fallback,
  lazy = false,
  loadingLabel,
}: AssetImageProps) {
  const placeholder = useRef<HTMLDivElement>(null);
  const near = useNearViewport(placeholder);
  const { src, failed } = useAssetImage(path, !lazy || near);
  if (!path || failed) return <>{fallback}</>;
  if (src) return <img src={src} alt={alt} decoding="async" className={className} />;
  return (
    <div
      ref={placeholder}
      role={loadingLabel ? 'img' : undefined}
      aria-label={loadingLabel}
      aria-hidden={loadingLabel ? undefined : true}
      className={cn('animate-pulse rounded-md bg-muted', placeholderClassName)}
    />
  );
}

import { Separator } from '@/components/ui/separator';
import type { WidgetRenderProps } from '../contract';
import type { SeparatorConfig } from './definition';

/** A horizontal rule readers' assistive technology announces as a separator; the gap style draws nothing. */
export function SeparatorBlockFallback({ config }: WidgetRenderProps<SeparatorConfig>) {
  return (
    <Separator
      decorative={false}
      className={config.style === 'gap' ? 'my-8 bg-transparent' : 'my-4'}
    />
  );
}

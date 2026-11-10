/**
 * The Data tab's height cap leaves the bottom space a floating launcher
 * (Ask AI) publishes as --floating-dock-inset, so the launcher doesn't cover
 * the pagination row.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@/test/test-utils';
import { DataTab } from '@/components/dataset/tabs/DataTab';

vi.mock('@/components/dataset/AttributeTable', () => ({
  AttributeTable: () => null,
}));
vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useAttributes: () => ({ data: undefined }),
}));

function root(container: HTMLElement): HTMLElement {
  return container.firstElementChild as HTMLElement;
}

describe('DataTab viewport cap', () => {
  it('reserves the floating dock inset under the table', () => {
    const { container } = render(<DataTab datasetId="ds" canEdit={false} />);
    expect(root(container).style.maxHeight).toContain('var(--floating-dock-inset, 1rem)');
  });

  it('reserves it in the expanded view too', () => {
    const { container } = render(<DataTab datasetId="ds" canEdit={false} expanded />);
    expect(root(container).style.height).toContain('var(--floating-dock-inset, 1rem)');
  });
});

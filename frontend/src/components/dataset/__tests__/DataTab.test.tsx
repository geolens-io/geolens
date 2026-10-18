/**
 * The Data tab's height cap leaves room at the bottom of the viewport for the
 * fixed Ask AI launcher a signed-in reader gets, so it doesn't cover the
 * pagination row.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@/test/test-utils';
import { DataTab } from '@/components/dataset/tabs/DataTab';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/components/dataset/AttributeTable', () => ({
  AttributeTable: () => null,
}));

function cap(container: HTMLElement): string {
  return (container.firstElementChild as HTMLElement).style.maxHeight;
}

describe('DataTab viewport cap', () => {
  afterEach(() => {
    useAuthStore.setState({ token: null });
  });

  it('reserves the launcher corner for a signed-in reader', () => {
    useAuthStore.setState({ token: 'tok' });
    const { container } = render(<DataTab datasetId="ds" canEdit={false} />);
    expect(cap(container)).toContain('5.5rem');
  });

  it('reserves it in the expanded view too', () => {
    useAuthStore.setState({ token: 'tok' });
    const { container } = render(<DataTab datasetId="ds" canEdit={false} expanded />);
    expect((container.firstElementChild as HTMLElement).style.height).toContain('5.5rem');
  });

  it('keeps the small gap for an anonymous reader', () => {
    useAuthStore.setState({ token: null });
    const { container } = render(<DataTab datasetId="ds" canEdit={false} />);
    expect(cap(container)).toContain('1rem');
    expect(cap(container)).not.toContain('5.5rem');
  });
});

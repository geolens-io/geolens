import { render, screen } from '@/test/test-utils';
import { Tabs, TabsList, TabsTrigger } from '../tabs';

describe('Tabs accessibility', () => {
  function renderTabs() {
    return render(
      <Tabs defaultValue="t1">
        <TabsList>
          <TabsTrigger value="t1">Tab 1</TabsTrigger>
          <TabsTrigger value="t2">Tab 2</TabsTrigger>
        </TabsList>
      </Tabs>
    );
  }

  describe('semantic roles', () => {
    it('exposes a tablist role with both tabs', () => {
      renderTabs();
      const tablist = screen.getByRole('tablist');
      expect(tablist).toBeInTheDocument();

      const tabs = screen.getAllByRole('tab');
      expect(tabs).toHaveLength(2);
      expect(tabs[0]).toHaveAccessibleName('Tab 1');
      expect(tabs[1]).toHaveAccessibleName('Tab 2');
    });
  });

  describe('A11Y-01: touch target height', () => {
    it('applies min-h-11 for mobile 44px touch target on tabs-list', () => {
      renderTabs();
      const tablist = screen.getByRole('tablist');
      // min-h-11 is gated behind the horizontal-orientation group-data variant
      expect(tablist.className).toContain('min-h-11');
    });

    it('restores compact sm:min-h-9 height on desktop', () => {
      renderTabs();
      const tablist = screen.getByRole('tablist');
      expect(tablist.className).toContain('sm:min-h-9');
    });
  });

  describe('A11Y-02: scroll affordance', () => {
    it('applies snap-x and snap-mandatory on tabs-list', () => {
      renderTabs();
      const tablist = screen.getByRole('tablist');
      expect(tablist).toHaveClass('snap-x');
      expect(tablist).toHaveClass('snap-mandatory');
    });

    it('applies snap-start on each tab trigger', () => {
      renderTabs();
      const tabs = screen.getAllByRole('tab');
      tabs.forEach((tab) => {
        expect(tab).toHaveClass('snap-start');
      });
    });

    it('renders a scroll wrapper with overflow-x-auto around the tablist', () => {
      renderTabs();
      const tablist = screen.getByRole('tablist');
      // The scroll wrapper is the tablist's parent element
      const scrollWrapper = tablist.parentElement;
      expect(scrollWrapper).not.toBeNull();
      expect(scrollWrapper).toHaveClass('overflow-x-auto');
    });
  });
});

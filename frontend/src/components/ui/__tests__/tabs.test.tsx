import { render } from '@/test/test-utils';
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

  describe('A11Y-01: touch target height', () => {
    it('applies min-h-11 for mobile 44px touch target on tabs-list', () => {
      renderTabs();
      const list = document.querySelector('[data-slot="tabs-list"]');
      expect(list).toBeTruthy();
      expect(list!.className).toContain('min-h-11');
    });

    it('restores compact sm:min-h-9 height on desktop', () => {
      renderTabs();
      const list = document.querySelector('[data-slot="tabs-list"]');
      expect(list).toBeTruthy();
      expect(list!.className).toContain('sm:min-h-9');
    });
  });

  describe('A11Y-02: scroll affordance', () => {
    it('applies snap-x and snap-mandatory on tabs-list', () => {
      renderTabs();
      const list = document.querySelector('[data-slot="tabs-list"]');
      expect(list).toBeTruthy();
      expect(list!.className).toContain('snap-x');
      expect(list!.className).toContain('snap-mandatory');
    });

    it('applies snap-start on tabs-trigger', () => {
      renderTabs();
      const trigger = document.querySelector('[data-slot="tabs-trigger"]');
      expect(trigger).toBeTruthy();
      expect(trigger!.className).toContain('snap-start');
    });

    it('renders a scroll wrapper with overflow-x-auto', () => {
      renderTabs();
      const scrollWrapper = document.querySelector('[data-slot="tabs-list-scroll"]');
      expect(scrollWrapper).toBeTruthy();
      expect(scrollWrapper!.className).toContain('overflow-x-auto');
    });
  });
});

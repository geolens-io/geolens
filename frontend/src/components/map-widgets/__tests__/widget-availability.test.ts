import '../register-widgets';
import {
  getDefaultWidgetIds,
  isWidgetIdAvailable,
  resolveAvailableWidgetIds,
  sameWidgetIds,
} from '../widget-availability';

describe('widget availability helpers', () => {
  it('treats null or undefined enabled widgets as no restriction', () => {
    expect(isWidgetIdAvailable('legend', null)).toBe(true);
    expect(isWidgetIdAvailable('measurement', undefined)).toBe(true);
  });

  it('filters unknown and admin-disabled IDs while preserving order', () => {
    expect(resolveAvailableWidgetIds(['unknown', 'measurement', 'legend', 'measurement'], ['legend', 'measurement'])).toEqual([
      'measurement',
      'legend',
    ]);
    expect(resolveAvailableWidgetIds(['measurement', 'legend'], ['legend'])).toEqual(['legend']);
  });

  it('resolves default visible widgets through admin enablement', () => {
    expect(getDefaultWidgetIds(null)).toEqual(['legend']);
    expect(getDefaultWidgetIds(['measurement'])).toEqual([]);
    expect(getDefaultWidgetIds(['legend'])).toEqual(['legend']);
  });

  it('compares widget ID arrays by exact saved order', () => {
    expect(sameWidgetIds(['legend', 'measurement'], ['legend', 'measurement'])).toBe(true);
    expect(sameWidgetIds(['measurement', 'legend'], ['legend', 'measurement'])).toBe(false);
  });
});

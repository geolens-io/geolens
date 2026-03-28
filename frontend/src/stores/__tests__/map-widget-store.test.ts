import { useWidgetStore } from '@/stores/map-widget-store';

const initialState = useWidgetStore.getState();

describe('useWidgetStore', () => {
  beforeEach(() => {
    useWidgetStore.setState(initialState, true);
  });

  it('starts with empty active widgets', () => {
    expect(useWidgetStore.getState().activeWidgets.size).toBe(0);
  });

  it('open adds a widget', () => {
    useWidgetStore.getState().open('test-widget');
    expect(useWidgetStore.getState().activeWidgets.has('test-widget')).toBe(true);
  });

  it('open is idempotent', () => {
    useWidgetStore.getState().open('test-widget');
    useWidgetStore.getState().open('test-widget');
    expect(useWidgetStore.getState().activeWidgets.size).toBe(1);
  });

  it('close removes a widget', () => {
    useWidgetStore.getState().open('test-widget');
    useWidgetStore.getState().close('test-widget');
    expect(useWidgetStore.getState().activeWidgets.has('test-widget')).toBe(false);
  });

  it('close on non-existent widget is a no-op', () => {
    useWidgetStore.getState().close('nonexistent');
    expect(useWidgetStore.getState().activeWidgets.size).toBe(0);
  });

  it('toggle opens a closed widget', () => {
    useWidgetStore.getState().toggle('test-widget');
    expect(useWidgetStore.getState().activeWidgets.has('test-widget')).toBe(true);
  });

  it('toggle closes an open widget', () => {
    useWidgetStore.getState().open('test-widget');
    useWidgetStore.getState().toggle('test-widget');
    expect(useWidgetStore.getState().activeWidgets.has('test-widget')).toBe(false);
  });

  it('manages multiple widgets independently', () => {
    const { open, close } = useWidgetStore.getState();
    open('a');
    open('b');
    open('c');
    close('b');

    const { activeWidgets } = useWidgetStore.getState();
    expect(activeWidgets.has('a')).toBe(true);
    expect(activeWidgets.has('b')).toBe(false);
    expect(activeWidgets.has('c')).toBe(true);
    expect(activeWidgets.size).toBe(2);
  });
});

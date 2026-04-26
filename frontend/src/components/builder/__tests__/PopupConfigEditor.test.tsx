import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { PopupConfigEditor } from '../PopupConfigEditor';
import type { PopupConfig } from '@/types/api';

// Radix Switch internally uses ResizeObserver in some setups
(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;

const COLUMNS = [
  { name: 'name', type: 'string' },
  { name: 'city', type: 'string' },
  { name: 'pop', type: 'integer' },
];

describe('PopupConfigEditor', () => {
  it('renders ENABLED state when popupConfig is null (default-on) and toggling off emits enabled:false', async () => {
    const onPopupChange = vi.fn();
    const user = userEvent.setup();

    render(
      <PopupConfigEditor columns={COLUMNS} popupConfig={null} onPopupChange={onPopupChange} />,
    );

    // Popups are enabled by default — null config behaves as enabled.
    const sw = screen.getByRole('switch');
    expect(sw).toHaveAttribute('aria-checked', 'true');

    // The expression input is visible (editor renders even when popupConfig is null)
    expect(screen.getByPlaceholderText(/\{city\}, \{state\}/i)).toBeInTheDocument();

    // Toggling off emits an explicit disabled config
    await user.click(sw);
    expect(onPopupChange).toHaveBeenCalledWith({
      enabled: false,
      expression: null,
      visible_fields: null,
    });
  });

  it('toggling off emits enabled:false and preserves expression / visible_fields', async () => {
    const onPopupChange = vi.fn();
    const user = userEvent.setup();
    const cfg: PopupConfig = {
      enabled: true,
      expression: '{name}',
      visible_fields: ['name', 'city'],
    };

    render(
      <PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={onPopupChange} />,
    );

    const sw = screen.getByRole('switch');
    await user.click(sw);

    expect(onPopupChange).toHaveBeenCalledWith({
      enabled: false,
      expression: '{name}',
      visible_fields: ['name', 'city'],
    });
  });

  it('shows validation error after debounce when an unknown placeholder is typed', async () => {
    vi.useFakeTimers();
    const onPopupChange = vi.fn();

    const cfg: PopupConfig = { enabled: true, expression: '', visible_fields: null };

    render(
      <PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={onPopupChange} />,
    );

    const input = screen.getByPlaceholderText(/\{city\}, \{state\}/i);
    // Use fireEvent.change to avoid userEvent's incompatibility with fake timers in this test
    fireEvent.change(input, { target: { value: '{nope}' } });

    // Before debounce window closes, helper text shows the OK help
    expect(screen.getByText(/Use \{column_name\} placeholders/i)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(screen.getByText(/Unknown placeholders: nope/i)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('switching to "Custom selection" mode emits visible_fields: []', async () => {
    const onPopupChange = vi.fn();
    const user = userEvent.setup();
    const cfg: PopupConfig = { enabled: true, expression: '', visible_fields: null };

    render(
      <PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={onPopupChange} />,
    );

    const customBtn = screen.getByRole('button', { name: /Custom selection/i });
    await user.click(customBtn);

    expect(onPopupChange).toHaveBeenCalledWith({
      enabled: true,
      expression: '',
      visible_fields: [],
    });
  });

  it('clicking an available column appends it to visible_fields in click order', async () => {
    const onPopupChange = vi.fn();
    const user = userEvent.setup();
    const cfg: PopupConfig = { enabled: true, expression: '', visible_fields: [] };

    render(
      <PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={onPopupChange} />,
    );

    const cityBtn = screen.getByRole('button', { name: 'city' });
    await user.click(cityBtn);

    expect(onPopupChange).toHaveBeenCalledWith({
      enabled: true,
      expression: '',
      visible_fields: ['city'],
    });
  });

  it('expression input has maxLength=500 to enforce the backend cap client-side', () => {
    const cfg: PopupConfig = { enabled: true, expression: '', visible_fields: null };
    render(<PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={vi.fn()} />);
    const input = screen.getByPlaceholderText(/\{city\}, \{state\}/i);
    expect(input).toHaveAttribute('maxLength', '500');
  });

  it('shows the noColumns empty-state message when custom mode is active and the layer has no columns', () => {
    const cfg: PopupConfig = { enabled: true, expression: '', visible_fields: [] };
    render(<PopupConfigEditor columns={[]} popupConfig={cfg} onPopupChange={vi.fn()} />);
    // i18n key has en value "This layer has no inspectable columns."
    expect(screen.getByText(/no inspectable columns/i)).toBeInTheDocument();
  });

  it('clearing the expression input emits expression: null (not empty string)', async () => {
    const onPopupChange = vi.fn();
    const cfg: PopupConfig = { enabled: true, expression: '{name}', visible_fields: null };
    render(<PopupConfigEditor columns={COLUMNS} popupConfig={cfg} onPopupChange={onPopupChange} />);
    const input = screen.getByPlaceholderText(/\{city\}, \{state\}/i);
    fireEvent.change(input, { target: { value: '' } });
    expect(onPopupChange).toHaveBeenCalledWith({
      enabled: true,
      expression: null,
      visible_fields: null,
    });
  });

  // Cleanup any leftover fake timers between tests
  beforeEach(() => {});
  afterEach(() => {
    vi.useRealTimers();
  });
});

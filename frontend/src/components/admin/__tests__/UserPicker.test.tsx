import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { onTestFinished } from 'vitest';
import { UserPicker } from '../UserPicker';

const USERS = [
  { id: 'u1', username: 'alice' },
  { id: 'u2', username: 'bob' },
  { id: 'u3', username: 'alicia' },
];

function setup() {
  const onSelect = vi.fn();
  const user = userEvent.setup();
  render(<UserPicker label="Add a person" users={USERS} onSelect={onSelect} />);
  return { onSelect, user, input: screen.getByRole('combobox', { name: 'Add a person' }) };
}

describe('UserPicker', () => {
  it('is a labelled combobox that starts collapsed', () => {
    const { input } = setup();
    expect(input).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens with ArrowDown and picks the active option with Enter', async () => {
    const { user, input, onSelect } = setup();
    await user.click(input);
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByRole('option')).toHaveLength(3);

    await user.keyboard('{ArrowDown}{Enter}');

    expect(onSelect).toHaveBeenCalledWith(USERS[1]);
    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
  });

  it('tracks the active option for assistive technology', async () => {
    const { user, input } = setup();
    await user.click(input);
    await user.keyboard('{ArrowDown}{ArrowDown}');
    const active = screen.getAllByRole('option').find((o) => o.getAttribute('aria-selected') === 'true');
    expect(input.getAttribute('aria-activedescendant')).toBe(active?.id);
    expect(active).toHaveTextContent('bob');
  });

  it('filters as the user types and reports no matches', async () => {
    const { user, input } = setup();
    await user.type(input, 'ali');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['alice', 'alicia']);

    await user.type(input, 'zzz');
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
    expect(screen.getByText('No matching people')).toBeInTheDocument();
  });

  it('closes the list on Escape and leaves the key for an enclosing dialog afterwards', async () => {
    const outer = vi.fn();
    const onSelect = vi.fn();
    const user = userEvent.setup();
    const listener = (e: KeyboardEvent) => e.key === 'Escape' && outer();
    document.addEventListener('keydown', listener);
    onTestFinished(() => document.removeEventListener('keydown', listener));
    render(<UserPicker label="Add a person" users={USERS} onSelect={onSelect} />);
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('{ArrowDown}');

    await user.keyboard('{Escape}');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(outer).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(outer).toHaveBeenCalledTimes(1);
  });

  it('selects an option with the mouse', async () => {
    const { user, input, onSelect } = setup();
    await user.click(input);
    await user.keyboard('{ArrowDown}');
    await user.click(screen.getByRole('option', { name: 'bob' }));
    expect(onSelect).toHaveBeenCalledWith(USERS[1]);
  });

  it('keeps the query and list, and reports busy, when a pick arrives while busy', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<UserPicker label="Add a person" users={USERS} onSelect={onSelect} busy />);
    const input = screen.getByRole('combobox');
    await user.type(input, 'ali');
    expect(input).toHaveAttribute('aria-busy', 'true');

    await user.click(screen.getByRole('option', { name: 'alicia' }));
    await user.keyboard('{Enter}');

    expect(onSelect).not.toHaveBeenCalled();
    expect(input).toHaveValue('ali');
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(input).toHaveFocus();
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-disabled', 'true');
  });
});

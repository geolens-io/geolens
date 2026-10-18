import { act } from '@testing-library/react';
import { render, screen } from '@/test/test-utils';
import { useAuthStore } from '@/stores/auth-store';
import { SectionCapabilityHint } from '../SectionCapabilityHint';

const readOnly = { editable: false, canAttempt: true, reason: 'insufficient_role' as const };

describe('SectionCapabilityHint', () => {
  afterEach(() => {
    act(() => {
      useAuthStore.setState({ token: null });
    });
  });

  it('shows the read-only hint to a signed-in user without edit rights', () => {
    act(() => {
      useAuthStore.setState({ token: 'token' });
    });
    render(<SectionCapabilityHint capability={readOnly} />);
    expect(screen.getByTestId('role-capability-hint')).toBeInTheDocument();
  });

  it('shows nothing to a signed-out visitor', () => {
    render(<SectionCapabilityHint capability={readOnly} />);
    expect(screen.queryByTestId('role-capability-hint')).not.toBeInTheDocument();
  });
});
